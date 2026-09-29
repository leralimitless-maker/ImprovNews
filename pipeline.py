"""Оркестрация: источники -> кэш -> генерация -> PDF -> доставка."""
import itertools

from cache import is_already_delivered_today, load_cache, run_stage, save_cache
from config import REDDIT_TEXT_BUDGET, RSS_TEXT_BUDGET, TG_TEXT_BUDGET, validate_env
from generation import build_full_newspaper
from publishing.drive import update_google_doc, upload_pdf_to_drive
from publishing.telegram import send_pdf_to_telegram
from rendering import render_pdf
from sources.reddit import fetch_reddit_posts
from sources.rss import fetch_rss_posts
from sources.telegram import fetch_channel_posts

def _truncate_at_boundary(text: str, budget: int) -> str:
    """Обрезает text до budget символов, но не посреди поста: если после обрезки последний
    пост оказался разорван, откатываемся к предыдущей границе "\\n\\n" между постами. Отрезанный
    хвост — не ошибка (см. вызывающий код: у каждого источника свой бюджет, это ожидаемая
    экономия лимитов API), поэтому явно помечаем его, а не молча теряем."""
    if len(text) <= budget:
        return text
    cut = text[:budget]
    boundary = cut.rfind("\n\n")
    if boundary > 0:
        cut = cut[:boundary]
    return cut.rstrip() + "\n\n[ОСТАЛЬНОЕ ОБРЕЗАНО ДЛЯ ЭКОНОМИИ ЛИМИТОВ API]"


def main():
    validate_env()  # ИЗМЕНЕНО (0.8): fail-fast до любой работы с сетью и кэшем
    cache = load_cache()

    # ИЗМЕНЕНО (0.2): вместо check_if_built_today() (PDF на Диске) смотрим на состояние этапов в кэше.
    if is_already_delivered_today(cache):
        print("Газета уже была успешно доставлена сегодня. Завершаю работу.", flush=True)
        return

    if cache["raw_news"]:
        print("Лента новостей загружена из локального дампа (пропуск парсинга).", flush=True)
        raw_news = cache["raw_news"]
    else:
        print("Парсинг источников...", flush=True)
        # Общий счётчик на весь запуск: у источника из ЛЮБОГО фетчера должен быть глобально
        # уникальный ID (Sxx), иначе "S1" из Телеграма и "S1" из Reddit схлопнутся в один
        # при объединении в общий словарь sources ниже.
        source_id_gen = itertools.count(1)
        tg_news, tg_photos, tg_sources = fetch_channel_posts(source_id_gen)
        reddit_news, reddit_sources = fetch_reddit_posts(source_id_gen)
        rss_news, rss_sources = fetch_rss_posts(source_id_gen)

        # ДОБАВЛЕНО (1.10/DAT-003): бюджет на источник применяется ДО склейки — раньше общий
        # лимит в 40000 символов срабатывал уже после неё и почти всегда съедал Reddit и
        # блоги целиком, потому что Телеграм (116 каналов) почти всегда длиннее их обоих
        # вместе взятых. Теперь ни один источник не может вытеснить остальные.
        tg_news = _truncate_at_boundary(tg_news, TG_TEXT_BUDGET)
        reddit_news = _truncate_at_boundary(reddit_news, REDDIT_TEXT_BUDGET)
        rss_news = _truncate_at_boundary(rss_news, RSS_TEXT_BUDGET)

        raw_news = f"Телеграм:\n{tg_news}\n\nReddit:\n{reddit_news}\n\nБлоги:\n{rss_news}"
        sources = {**tg_sources, **reddit_sources, **rss_sources}

        if tg_news.strip() or reddit_news.strip() or rss_news.strip():
            # raw_news, photos и sources сохраняются вместе: раздельные save_cache() между
            # ними оставили бы окно, в котором на диске лежат ID без самих значений (при
            # падении между записями) — тогда при перезапуске из кэша они бы не нашлись.
            cache["raw_news"] = raw_news
            cache["photos"] = tg_photos
            cache["sources"] = sources
            save_cache(cache)
        else:
            raw_news = ""

    if raw_news.strip():
        print("Запуск модульного конвейера Gemini...", flush=True)
        draft_html = build_full_newspaper(raw_news, cache)
        
        if draft_html:
            print("Создание PDF-версии...", flush=True)
            pdf_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    @page {{ size: A4; margin: 15mm; }}
                    body {{ background-color: #ffffff; line-height: 1.5; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #222; }}
                    img {{ max-width: 100%; max-height: 400px; object-fit: cover; display: block; margin: 0 0 10px 0; border-radius: 6px; }}
                    table {{ page-break-inside: auto; width: 100%; }}
                    tr {{ page-break-inside: avoid; }}
                    h1, h2, h3 {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #000; }}
                </style>
            </head>
            <body>
                {draft_html}
            </body>
            </html>
            """
            pdf_path = "newspaper.pdf"
            # ДОБАВЛЕНО (1.4): вместо HTML(...).write_pdf() — render_pdf с SafeImageFetcher
            # (белый список хостов, лимиты размера/времени, проверка формата по содержимому).
            render_pdf(pdf_html, pdf_path)

            # ИЗМЕНЕНО (0.2): каждый этап пишет свой результат в cache["stages"];
            # уже успешные при повторном запуске пропускаются.
            run_stage(cache, "drive_doc", "Загрузка черновика в Google Docs", update_google_doc, draft_html)
            run_stage(cache, "drive_pdf", "Загрузка PDF на Google Диск", upload_pdf_to_drive, pdf_path)
            run_stage(cache, "telegram", "Отправка PDF в Telegram", send_pdf_to_telegram, pdf_path)

            if is_already_delivered_today(cache):
                print("Успешно завершено!", flush=True)
            else:
                # Ненулевой код выхода — чтобы GitHub Actions/ретрай увидели сбой,
                # а не "зелёный" запуск с потерянной доставкой.
                print(f"Пайплайн завершился частично: {cache['stages']}", flush=True)
                raise SystemExit(1)
        else:
            print("Газета не собрана: во всех рубриках сработал NO_CONTENT.", flush=True)
    else:
        print("Внимание: За последние 24 часа не найдено ни одного нового поста.", flush=True)

if __name__ == "__main__":
    main()

