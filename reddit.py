"""Источник: Reddit."""
from datetime import datetime, timezone

import requests

from config import LOCAL_TZ
from http_client import HTTP_SESSION
from text_safety import _strip_fake_provenance_tags

# ИСПРАВЛЕНО (CRT-1/REL-002, MED-5): во всех трёх fetch_* стояли голые `except: pass`.
# Они проглатывали ВСЁ подряд (включая KeyboardInterrupt) и без единой строки в логе, а
# try охватывал целиком канал/фид — один битый пост (кривая дата, неожиданная разметка)
# выбрасывал все остальные посты того же источника. Теперь:
#   1) сетевые ошибки ловятся точечно (requests.RequestException) и пишутся в лог;
#   2) каждый пост/запись обрабатывается в своём try — сбой одного не трогает соседей.


def _format_unix_local(ts) -> str:
    """UNIX-время -> «ДД.ММ» в локальной таймзоне; при отсутствии/битом значении — пустая строка."""
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).astimezone(LOCAL_TZ).strftime("%d.%m")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def fetch_reddit_posts(source_id_gen):
    """source_id_gen — общий на весь запуск счётчик (см. main()): у источника из любого
    фетчера (Телеграм/Reddit/RSS) должен быть глобально уникальный ID вида Sxx.
    Возвращает (текст_постов, sources): sources — {ID: "r/improv, 21.09"} для атрибуции."""
    reddit_url = "https://www.reddit.com/r/improv/top.json?limit=5&t=week"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ImprovNewspaperBot/1.0"}
    reddit_texts = []
    sources = {}
    try:
        response = HTTP_SESSION.get(reddit_url, headers=headers, timeout=30)
        response.raise_for_status()
        children = (response.json().get('data') or {}).get('children', [])
    except (requests.RequestException, ValueError, AttributeError) as e:
        print(f"[!] Reddit недоступен или вернул неожиданный ответ: {e}", flush=True)
        return "", sources
    for post in children:
        try:
            data = post.get('data', {})
            title = _strip_fake_provenance_tags(data.get('title', ''))
            text = _strip_fake_provenance_tags(data.get('selftext', ''))
            if not title:
                continue
            subreddit = data.get('subreddit') or 'improv'
            when = _format_unix_local(data.get('created_utc'))
            label = f"r/{subreddit}, {when}" if when else f"r/{subreddit}"
            source_id = f"S{next(source_id_gen)}"
            sources[source_id] = label
            reddit_texts.append(f"[Пост {source_id} от {label}]\n{title}\n{text[:1000]}...")
        except Exception as e:
            print(f"[!] Пропущен пост Reddit: {e}", flush=True)
    return "\n\n".join(reddit_texts), sources
