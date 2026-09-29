"""Кэш дня: сырые новости, сгенерированные рубрики и состояние этапов доставки."""
import json
import os
import tempfile
from datetime import datetime

from config import CACHE_FILE, LOCAL_TZ

# ДОБАВЛЕНО: единая точка получения "сегодня" в часовом поясе редакции (LOCAL_TZ).
# Вынесено в отдельную функцию, чтобы дата в кэше и дата, с которой её сравнивают,
# всегда считались одинаково (одна и та же формула, один и тот же часовой пояс).
def _today_str() -> str:
    return datetime.now(LOCAL_TZ).date().isoformat()


# ИСПРАВЛЕНО (BLK-1 — главный баг из ревью): раньше load_cache() возвращал содержимое
# файла как есть, без проверки, на какую дату оно относится. Из-за этого, если файл
# кэша переживал между запусками (а именно для этого он и был задуман — см. комментарий
# в build_full_newspaper про "повторную попытку"), на СЛЕДУЮЩИЙ календарный день скрипт
# находил непустой cache["raw_news"]/cache["sections"] от вчерашнего выпуска, считал,
# что "новости уже загружены"/"рубрика уже сгенерирована", и публиковал вчерашнюю
# газету как сегодняшнюю — бесконечно, пока кто-то не удалит файл кэша вручную.
#
# Теперь в кэш всегда пишется дата (см. save_cache), и если она не совпадает с
# сегодняшней (либо кэш вообще без поля "date" — старый формат или чужой файл),
# кэш считается устаревшим и load_cache() возвращает чистое состояние.
#
# Также убран голый except: pass — он ловил вообще любое исключение (включая
# KeyboardInterrupt/SystemExit) и молчал. Теперь ловятся конкретно OSError
# (проблемы с файловой системой: нет прав, диск отвалился и т.п.) и
# json.JSONDecodeError (битый/обрезанный JSON), и причина явно попадает в лог —
# это как раз тот случай, когда кэш мог испортиться при обрыве записи посреди
# json.dump в старой версии save_cache (см. ниже).
#
# ДОБАВЛЕНО (1.1–1.3): версия формата кэша. Секции теперь кэшируются как HTML, собранный
# из JSON-ответа модели, а в raw_news вместо URL фото лежат ID (P1, P2...) + отдельный
# словарь "photos". Кэш старого формата (HTML от модели, URL прямо в тексте) несовместим,
# поэтому при несовпадении версии он считается устаревшим — так же, как кэш за вчера.
# Единственная цена: если обновление кода придётся на день, когда выпуск уже доставлен,
# повторный запуск в тот же день соберёт и отправит газету ещё раз.
# ДОБАВЛЕНО: версия 3 — в raw_news каждый пост теперь обёрнут тегом «[Пост Sxx от ...]»
# (атрибуция источника перед постом), а не старым «[Канал X]:». Сама по себе рассинхронизация
# не ломает пайплайн (модель просто не найдёт тегов и оставит source_id пустым — see
# SYSTEM_INSTRUCTION), но раз уж кэш всё равно инвалидируется по формату — заодно и здесь:
# кэш с версии 2 (сырые новости без новых тегов) сброшен, чтобы атрибуция сразу заработала
# в тот же день, когда выкатили эту версию, а не только со следующего дня.
CACHE_VERSION = 3


def load_cache() -> dict:
    today = _today_str()
    empty_cache = {"version": CACHE_VERSION, "date": today, "raw_news": None,
                   "photos": {}, "sources": {}, "sections": {}, "stages": {}}

    if not os.path.exists(CACHE_FILE):
        return empty_cache

    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[!] Кэш повреждён или недоступен ({e}), начинаю сборку заново.", flush=True)
        return empty_cache

    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        version = data.get("version") if isinstance(data, dict) else None
        print(f"[i] Кэш старого формата (version={version!r}, нужен {CACHE_VERSION}) — начинаю сборку заново.", flush=True)
        return empty_cache

    if data.get("date") != today:
        print(f"[i] Кэш относится к {data.get('date')!r}, сегодня {today} — начинаю сборку заново.", flush=True)
        return empty_cache

    # Кэш сегодняшний и актуального формата; поля добавлены на случай ручной правки файла.
    data.setdefault("stages", {})
    data.setdefault("photos", {})
    data.setdefault("sources", {})
    data.setdefault("sections", {})
    return data


# ИСПРАВЛЕНО (BLK-2, CRT-3/REL-003): раньше единственным признаком "газета уже
# доставлена" был файл newspaper.pdf в папке на Google Диске с сегодняшним modifiedTime
# (см. check_if_built_today). Но PDF загружается на Диск ДО отправки в Telegram:
# если Telegram падал (а его ответ вообще не проверялся), Диск уже "сообщал", что
# выпуск готов, и все последующие запуски дня молча завершались, ничего не отправив.
# Теперь источник правды — состояние этапов доставки в кэше: каждый этап помечается
# True только после реального успеха, и запуск считается завершённым, только когда
# успешны ВСЕ этапы.
DELIVERY_STAGES = ("drive_doc", "drive_pdf", "telegram")


def is_already_delivered_today(cache: dict) -> bool:
    stages = cache.get("stages", {})
    return cache.get("date") == _today_str() and all(stages.get(name) is True for name in DELIVERY_STAGES)


def run_stage(cache: dict, name: str, label: str, action, *args) -> None:
    """Выполняет этап доставки, если он ещё не пройден сегодня, и сразу сохраняет результат.
    Уже успешные этапы при повторном запуске пропускаются (не шлём дубль в Telegram
    только из-за того, что упал Google Drive, и наоборот)."""
    stages = cache["stages"]
    if stages.get(name) is True:
        print(f"{label}: уже выполнено сегодня, пропуск.", flush=True)
        return
    print(f"{label}...", flush=True)
    stages[name] = bool(action(*args))
    save_cache(cache)


# ИСПРАВЛЕНО (HIGH-1/REL-004): раньше запись шла напрямую в CACHE_FILE через
# open(..., "w"). Если процесс оборвётся посреди json.dump (краш, OOM-killer,
# обрыв раннера CI) — файл останется наполовину записанным, с битым JSON.
# А поскольку старый load_cache() глотал любую ошибку чтения (см. выше),
# это привело бы к тихой потере всего прогресса дня без единого предупреждения.
#
# Теперь запись атомарна: сначала пишем во временный файл В ТОЙ ЖЕ директории
# (это важно — os.replace должен работать в пределах одной файловой системы),
# затем одним системным вызовом os.replace() подменяем им CACHE_FILE.
# os.replace() атомарен и на POSIX, и на Windows: в CACHE_FILE в любой момент
# времени лежит либо полностью старое содержимое, либо полностью новое —
# промежуточного "наполовину записанного" состояния снаружи никогда не видно.
#
# Также добавлено автоматическое проставление сегодняшней даты в cache_data,
# если вызывающий код сам её не передал — чтобы дата в файле не могла "отстать"
# от момента фактической записи.
def save_cache(cache_data: dict) -> None:
    cache_data.setdefault("date", _today_str())
    cache_data.setdefault("version", CACHE_VERSION)

    cache_dir = os.path.dirname(CACHE_FILE) or "."
    fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=4)
        os.replace(tmp_path, CACHE_FILE)
    finally:
        # Если что-то пошло не так до os.replace (например, диск заполнился
        # посреди json.dump) — не оставляем за собой мусорный .tmp-файл.
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
