"""Источник: публичные Telegram-каналы (t.me/s/...)."""
import hashlib
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from config import CHANNELS, LOCAL_TZ
from http_client import HTTP_SESSION
from rendering import is_allowed_image_url
from text_safety import _strip_fake_provenance_tags

# ИСПРАВЛЕНО (DAT-002): datetime.fromisoformat() без таймзоны в строке даёт "наивный"
# datetime, а .astimezone() для наивного трактует его как ЛОКАЛЬНОЕ время машины —
# то есть результат зависит от TZ раннера. Наивные даты явно считаем UTC.
def _to_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

# ДОБАВЛЕНО (1.9/DAT-003): один и тот же текст нередко форвардят в десятки каналов сразу
# (мемы, анонсы, новости индустрии) — без дедупликации это не "разные новости", а один и
# тот же пост, посчитанный N раз, который вытесняет из бюджета символов (см. TG_TEXT_BUDGET
# выше) реально разные посты и может заставить модель посвятить рубрику одному инфоповоду.
_URL_RE = re.compile(r"https?://\S+")
_MIN_DEDUP_KEY_LEN = 20  # короче — слишком много случайных совпадений между РАЗНЫМИ постами


def _dedup_key(text: str) -> str:
    """Ключ для грубой дедупликации репостов: без ссылок (у каждого форварда обычно свои
    UTM/реф-метки) и без различий в пробелах/регистре. Пустая строка означает «не дедуплицировать
    по этому ключу» — так помечены слишком короткие тексты (см. _MIN_DEDUP_KEY_LEN), чтобы,
    например, два разных поста с одной лишь подписью "🔥" не схлопнулись в один дубль.
    Ограничение: ловит только ДОСЛОВНЫЙ форвард, не перефразированный репост и не пост с
    добавленной "шапкой" канала перед тем же текстом — это осознанный компромисс простоты."""
    normalized = " ".join(_URL_RE.sub("", text).split()).strip().lower()
    if len(normalized) < _MIN_DEDUP_KEY_LEN:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def fetch_channel_posts(source_id_gen):
    """Возвращает (текст_постов, photos, sources): в тексте вместо URL фото — идентификатор
    [Фото: P12] (сам URL — в photos[id], см. 1.1), а перед каждым постом — тег атрибуции
    «[Пост S7 от @channel, 14:02]» (сама подпись — в sources[id]). source_id_gen — общий на
    весь запуск счётчик (см. main()), чтобы ID не пересекались между Телеграмом/Reddit/RSS.
    Дословные повторы одного поста в нескольких каналах схлопываются в один (см. _dedup_key)."""
    # Собираем ВСЕХ кандидатов первым проходом, до раздачи Sxx/Pxx: иначе дубли, отсеянные
    # вторым проходом, оставляли бы в sources/photos "осиротевшие" записи и портили нумерацию.
    candidates = []  # (channel, post_date, text, allowed_img_url_or_empty)
    yesterday = datetime.now(LOCAL_TZ) - timedelta(hours=24)
    headers = {"User-Agent": "Mozilla/5.0"}
    # HTTP_SESSION переиспользует соединение с t.me между каналами и добавляет ретраи на
    # транспортном уровне (1.5); параллелизм между каналами — фаза 2.
    for channel in CHANNELS:
        try:
            response = HTTP_SESSION.get(f"https://t.me/s/{channel}", headers=headers, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"[!] Канал {channel} недоступен: {e}", flush=True)
            time.sleep(1)
            continue

        soup = BeautifulSoup(response.text, 'html.parser')
        for msg in soup.find_all('div', class_='tgme_widget_message'):
            try:
                time_tag = msg.select_one('.tgme_widget_message_date time') or msg.find('time')
                if not (time_tag and time_tag.has_attr('datetime')):
                    continue
                post_date = _to_aware_utc(
                    datetime.fromisoformat(time_tag['datetime'].replace('Z', '+00:00'))
                ).astimezone(LOCAL_TZ)
                if post_date < yesterday:
                    continue

                text_div = msg.find('div', class_='tgme_widget_message_text')
                text = _strip_fake_provenance_tags(
                    text_div.get_text(separator=' ', strip=True) if text_div else ""
                )

                img_url = ""
                photo_wrap = msg.find('a', class_='tgme_widget_message_photo_wrap')
                if photo_wrap and "background-image:url('" in photo_wrap.get('style', ''):
                    img_url = photo_wrap['style'].split("background-image:url('")[1].split("')")[0]

                allowed_img_url = ""
                if img_url:
                    if is_allowed_image_url(img_url):
                        allowed_img_url = img_url
                    else:
                        print(f"[!] Канал {channel}: URL фото вне белого списка CDN, пропущено.", flush=True)

                if not (len(text) > 30 or allowed_img_url):
                    continue
                candidates.append((channel, post_date, text, allowed_img_url))
            except Exception as e:
                print(f"[!] Пропущен пост в канале {channel}: {e}", flush=True)
        time.sleep(1)

    collected_texts = []
    photos = {}
    sources = {}
    seen_keys = set()
    duplicates = 0
    for channel, post_date, text, allowed_img_url in candidates:
        key = _dedup_key(text)
        if key:
            if key in seen_keys:
                duplicates += 1
                continue
            seen_keys.add(key)

        photo_tag = ""
        if allowed_img_url:
            photo_id = f"P{len(photos) + 1}"
            photos[photo_id] = allowed_img_url
            photo_tag = f"\n[Фото: {photo_id}]"

        source_id = f"S{next(source_id_gen)}"
        label = f"@{channel}, {post_date:%H:%M}"
        sources[source_id] = label
        collected_texts.append(f"[Пост {source_id} от {label}]\n{text}" + photo_tag)

    if duplicates:
        print(f"[i] Пропущено репостов-дублей: {duplicates}.", flush=True)

    return "\n\n".join(collected_texts), photos, sources
