"""Источник: Reddit."""
import calendar
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

try:
    import feedparser
    from bs4 import BeautifulSoup
except ImportError:
    feedparser = None
    BeautifulSoup = None

try:
    import requests
except ImportError:
    requests = None

from config import DEFAULT_HTTP_TIMEOUT, DEFAULT_USER_AGENT, LOCAL_TZ
from http_client import HTTP_SESSION
from text_safety import _strip_fake_provenance_tags

# ИСПРАВЛЕНО (CRT-1/REL-002, MED-5): во всех трёх fetch_* стояли голые `except: pass`.
# Они проглатывали ВСЁ подряд (включая KeyboardInterrupt) и без единой строки в логе, а
# try охватывал целиком канал/фид — один битый пост (кривая дата, неожиданная разметка)
# выбрасывал все остальные посты того же источника. Теперь:
#   1) сетевые ошибки ловятся точечно (requests.RequestException) и пишутся в лог;
#   2) каждый пост/запись обрабатывается в своём try — сбой одного не трогает соседей.


def _format_unix_local(ts: Any) -> str:
    """UNIX-время -> «ДД.ММ» в локальной таймзоне; при отсутствии/битом значении — пустая строка."""
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).astimezone(LOCAL_TZ).strftime("%d.%m")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _fetch_reddit_json(headers: dict[str, str]) -> list[dict[str, str]]:
    """Попытка получить посты r/improv через публичный JSON API."""
    if HTTP_SESSION is None:
        return []
    url = "https://www.reddit.com/r/improv/top.json?limit=5&t=week"
    response = HTTP_SESSION.get(url, headers=headers, timeout=DEFAULT_HTTP_TIMEOUT)
    response.raise_for_status()
    children = (response.json().get("data") or {}).get("children", [])
    posts = []
    for item in children:
        data = item.get("data", {})
        title = _strip_fake_provenance_tags(data.get("title", ""))
        text = _strip_fake_provenance_tags(data.get("selftext", ""))
        if not title:
            continue
        subreddit = data.get("subreddit") or "improv"
        when = _format_unix_local(data.get("created_utc"))
        label = f"r/{subreddit}, {when}" if when else f"r/{subreddit}"
        posts.append({"title": title, "text": text, "label": label})
    return posts


def _fetch_reddit_rss(headers: dict[str, str]) -> list[dict[str, str]]:
    """Резервный сбор постов r/improv через RSS/Atom-фид при блокировках JSON API (429/капча)."""
    if HTTP_SESSION is None or feedparser is None or BeautifulSoup is None:
        return []
    url = "https://www.reddit.com/r/improv/top/.rss?t=week"
    response = HTTP_SESSION.get(url, headers=headers, timeout=DEFAULT_HTTP_TIMEOUT)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    posts = []
    for entry in getattr(feed, "entries", [])[:5]:
        title = _strip_fake_provenance_tags(getattr(entry, "title", ""))
        if not title:
            continue
        raw_html = getattr(entry, "summary", "") or ""
        text = _strip_fake_provenance_tags(
            BeautifulSoup(raw_html, "html.parser").get_text(separator=" ", strip=True)
        )
        date_struct = getattr(entry, "updated_parsed", None) or getattr(entry, "published_parsed", None)
        when = ""
        if date_struct:
            try:
                dt = datetime.fromtimestamp(calendar.timegm(date_struct), timezone.utc).astimezone(LOCAL_TZ)
                when = dt.strftime("%d.%m")
            except Exception:
                pass
        label = f"r/improv, {when}" if when else "r/improv"
        posts.append({"title": title, "text": text, "label": label})
    return posts


def fetch_reddit_posts(source_id_gen: Iterator[int]) -> tuple[str, dict[str, str]]:
    """source_id_gen — общий на весь запуск счётчик (см. main()): у источника из любого
    фетчера (Телеграм/Reddit/RSS) должен быть глобально уникальный ID вида Sxx.
    Возвращает (текст_постов, sources): sources — {ID: "r/improv, 21.09"} для атрибуции.
    При сбое или 429 от JSON API автоматически переключается на резервный RSS-фид."""
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    sources: dict[str, str] = {}
    posts_data = []

    # 1. Основной путь: JSON API
    try:
        posts_data = _fetch_reddit_json(headers)
    except Exception as json_err:
        print(f"[!] Reddit JSON API недоступен ({json_err}), переключаемся на резервный RSS-фид...", flush=True)
        # 2. Резервный путь: RSS
        try:
            posts_data = _fetch_reddit_rss(headers)
            if posts_data:
                print(f"[*] Успешно получено {len(posts_data)} постов Reddit через резервный RSS-фид.", flush=True)
        except Exception as rss_err:
            print(f"[!] Reddit RSS-фид также недоступен ({rss_err}).", flush=True)
            return "", sources

    reddit_texts = []
    for item in posts_data:
        try:
            title = item["title"]
            text = item["text"]
            label = item["label"]
            source_id = f"S{next(source_id_gen)}"
            sources[source_id] = label
            reddit_texts.append(f"[Пост {source_id} от {label}]\n{title}\n{text[:1000]}...")
        except Exception as e:
            print(f"[!] Пропущен пост Reddit: {e}", flush=True)

    return "\n\n".join(reddit_texts), sources

