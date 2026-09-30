"""Отправка готового PDF в Telegram с датой выпуска и анонсом."""
import html
import re
from datetime import datetime
import requests
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from config import BOT_TOKEN, LOCAL_TZ, MY_CHAT_ID, is_empty_section
from http_client import HTTP_SESSION

MONTHS_RU = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря"
]


RUBRICS_PREFIX_PATTERN = re.compile(
    r'^(?:радар\s+импровизатора|кузница\s+кадров|анализ\s+и\s+механики|исповедь\s+из-за\s+кулис|цех\s+абсурда|что\s+по\s+сплетням\??|мастерская|практикум)\s*[:—–-]?\s*',
    re.IGNORECASE
)


def _clean_headline(raw: str) -> str:
    """Очищает заголовок от HTML, удаляет префиксы рубрик и кавычки."""
    text = re.sub(r'<[^>]+>', '', raw).strip()
    text = html.unescape(text)
    text = RUBRICS_PREFIX_PATTERN.sub('', text).strip()
    text = text.strip('«»"\' ')
    if len(text) > 75:
        text = text[:72].rstrip() + "..."
    return text


def generate_telegram_caption(cache: dict = None) -> str:
    """Формирует подпись к PDF: дата выпуска и самые интересные заголовки без названий рубрик."""
    now = datetime.now(LOCAL_TZ)
    date_str = f"{now.day} {MONTHS_RU[now.month - 1]} {now.year}"
    header = f"📰 IMPROVNEWS • {date_str}"

    bullets = []
    seen = set()
    if cache and isinstance(cache.get("sections"), dict):
        for title, html_content in cache["sections"].items():
            if is_empty_section(html_content):
                continue
            # Ищем заголовки h3 внутри рубрики
            matches = re.findall(r'<h3[^>]*>(.*?)</h3>', html_content, re.IGNORECASE | re.DOTALL)
            for m in matches:
                clean_title = _clean_headline(m)
                if len(clean_title) >= 10 and clean_title.lower() not in seen:
                    seen.add(clean_title.lower())
                    bullets.append(f"• {clean_title}")
                    break  # берём главный заголовок из каждой непустой рубрики

    if bullets:
        body = "В этом выпуске:\n" + "\n".join(bullets[:5])
    else:
        body = "Свежий выпуск независимого дайджеста импровизации готов к чтению!"

    full_caption = f"{header}\n\n{body}"
    return full_caption[:1020]


def _is_retryable_telegram_error(e: Exception) -> bool:
    return isinstance(e, requests.RequestException)


def _log_telegram_retry(retry_state) -> None:
    exc_type = type(retry_state.outcome.exception()).__name__
    wait = retry_state.next_action.sleep if retry_state.next_action else 0
    print(f"[!] Telegram недоступен ({exc_type}), повтор через {wait:.0f}с "
          f"(попытка {retry_state.attempt_number}/3)...", flush=True)


@retry(
    retry=retry_if_exception(_is_retryable_telegram_error),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(3),
    before_sleep=_log_telegram_retry,
    reraise=True,
)
def _post_document_to_telegram(url, data, pdf_path):
    with open(pdf_path, "rb") as doc:
        resp = HTTP_SESSION.post(url, data=data, files={"document": doc}, timeout=60)
    resp.raise_for_status()
    return resp


def send_pdf_to_telegram(pdf_path, cache: dict = None) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    caption = generate_telegram_caption(cache)
    try:
        resp = _post_document_to_telegram(url, {"chat_id": MY_CHAT_ID, "caption": caption}, pdf_path)
        if not resp.json().get("ok"):
            print(f"[!] Telegram вернул ok=false: {resp.text[:300]}", flush=True)
            return False
        return True
    except requests.exceptions.HTTPError as e:
        status = getattr(e.response, "status_code", "Unknown")
        err_desc = ""
        try:
            err_json = e.response.json()
            err_desc = f": {err_json.get('description', '')}"
        except Exception:
            pass
        print(f"[!] Ошибка отправки в Telegram (HTTP {status}{err_desc})", flush=True)
        return False
    except (requests.RequestException, OSError, ValueError) as e:
        print(f"[!] Ошибка отправки в Telegram: {type(e).__name__}", flush=True)
        return False
