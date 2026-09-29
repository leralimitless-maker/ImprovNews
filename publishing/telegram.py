"""Отправка готового PDF в Telegram."""
import requests
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from config import BOT_TOKEN, DOC_ID, MY_CHAT_ID
from http_client import HTTP_SESSION

# ИСПРАВЛЕНО (HIGH-3/REL-001, 0.6 — сделано здесь, т.к. этап "telegram" в 0.2 без этого
# был бы недостоверным): раньше ответ Telegram не проверялся вообще, и "Успешно завершено!"
# печаталось даже при неверном chat_id/токене. Теперь проверяются HTTP-статус и поле ok.
# В лог не попадает текст исключения: в нём есть URL с BOT_TOKEN.
def _is_retryable_telegram_error(e: Exception) -> bool:
    return isinstance(e, requests.RequestException)


def _log_telegram_retry(retry_state) -> None:
    # НЕ печатаем str(исключения): у requests.RequestException оно нередко включает сам URL
    # запроса, а он у нас содержит BOT_TOKEN. Тип исключения безопасен и достаточен для лога.
    exc_type = type(retry_state.outcome.exception()).__name__
    wait = retry_state.next_action.sleep if retry_state.next_action else 0
    print(f"[!] Telegram недоступен ({exc_type}), повтор через {wait:.0f}с "
          f"(попытка {retry_state.attempt_number}/3)...", flush=True)


# ДОБАВЛЕНО (1.7): сетевой вызов обёрнут tenacity ПОВЕРХ транспортных ретраев HTTP_SESSION
# (1.5) — короткие и быстрые ретраи urllib3 (доли секунды — единицы секунд на обрыв TCP/
# единичный 5xx) не всегда успевают "переждать" более длинную деградацию сервиса; здесь —
# на случай, если её всё же не хватило. Отдельная функция, а не весь send_pdf_to_telegram
# целиком: чтобы повторялся только сетевой запрос, а не логика вокруг него.
@retry(
    retry=retry_if_exception(_is_retryable_telegram_error),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(3),
    before_sleep=_log_telegram_retry,
    reraise=True,
)
def _post_document_to_telegram(url, data, pdf_path):
    # Файл открываем заново на каждую попытку: requests должен собрать multipart-тело из ещё
    # не прочитанного файлового объекта (после первой попытки курсор был бы в конце файла).
    with open(pdf_path, "rb") as doc:
        resp = HTTP_SESSION.post(url, data=data, files={"document": doc}, timeout=60)
    resp.raise_for_status()
    return resp


def send_pdf_to_telegram(pdf_path) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    caption = f"📰 Утренняя газета готова!\n\nРедактировать черновик:\nhttps://docs.google.com/document/d/{DOC_ID}/edit"
    try:
        resp = _post_document_to_telegram(url, {"chat_id": MY_CHAT_ID, "caption": caption}, pdf_path)
        if not resp.json().get("ok"):
            print(f"[!] Telegram вернул ok=false: {resp.text[:300]}", flush=True)
            return False
        return True
    except (requests.RequestException, OSError, ValueError) as e:
        print(f"[!] Ошибка отправки в Telegram: {type(e).__name__}", flush=True)
        return False
