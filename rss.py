"""Источник: RSS-блоги."""
import calendar
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import feedparser
import requests
from bs4 import BeautifulSoup

from config import LOCAL_TZ, RSS_FEEDS
from http_client import HTTP_SESSION
from text_safety import _strip_fake_provenance_tags

def _domain_label(url: str) -> str:
    """Короткое имя для атрибуции блога, когда в самом фиде нет <title> канала."""
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        host = ""
    return host.removeprefix("www.") or "Блог"


# ИСПРАВЛЕНО (CRT-2/REL-005): feedparser.parse(url) сам ходит в сеть БЕЗ таймаута — один
# зависший фид мог подвесить весь запуск навсегда (в CI — до лимита времени job'а).
# Теперь скачиваем сами через requests с таймаутом и отдаём feedparser'у готовые байты.
def fetch_rss_posts(source_id_gen):
    """Возвращает (текст_постов, sources); source_id_gen — см. fetch_reddit_posts."""
    collected_texts = []
    sources = {}
    yesterday = datetime.now(LOCAL_TZ) - timedelta(hours=24)
    for feed_url in RSS_FEEDS:
        try:
            resp = HTTP_SESSION.get(feed_url, timeout=15, headers={"User-Agent": "ImprovNewspaperBot/1.0"})
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except requests.RequestException as e:
            print(f"[!] RSS {feed_url} недоступен: {e}", flush=True)
            continue
        blog_name = _strip_fake_provenance_tags((feed.feed.get('title') or '').strip()) or _domain_label(feed_url)
        for entry in feed.entries:
            try:
                date_struct = getattr(entry, 'published_parsed', None) or getattr(entry, 'updated_parsed', None)
                if not date_struct:
                    continue
                dt = datetime.fromtimestamp(calendar.timegm(date_struct), timezone.utc).astimezone(LOCAL_TZ)
                if dt >= yesterday:
                    title = _strip_fake_provenance_tags(getattr(entry, 'title', ''))
                    text = _strip_fake_provenance_tags(
                        BeautifulSoup(getattr(entry, 'summary', ''), 'html.parser').get_text(separator=' ', strip=True)
                    )[:1000]
                    label = f"{blog_name}, {dt:%d.%m}"
                    source_id = f"S{next(source_id_gen)}"
                    sources[source_id] = label
                    collected_texts.append(f"[Пост {source_id} от {label}]\n{title}\n{text}...")
            except Exception as e:
                print(f"[!] Пропущена запись в {feed_url}: {e}", flush=True)
    return "\n\n".join(collected_texts), sources
