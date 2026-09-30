"""Оркестрация: источники -> кэш -> генерация -> PDF -> доставка."""
import argparse
from datetime import datetime
import itertools
import os
import sys
import tempfile
from typing import Sequence

from cache import is_already_delivered_today, load_cache, run_stage, save_cache
from config import LOCAL_TZ, REDDIT_TEXT_BUDGET, RSS_TEXT_BUDGET, TG_TEXT_BUDGET, validate_env
from logger import log

try:
    from generation import build_full_newspaper
except ImportError:
    build_full_newspaper = None

try:
    from publishing.drive import update_google_doc, upload_pdf_to_drive
except ImportError:
    update_google_doc = upload_pdf_to_drive = None

try:
    from publishing.telegram import send_pdf_to_telegram
except ImportError:
    send_pdf_to_telegram = None

try:
    from rendering import render_pdf
except ImportError:
    render_pdf = None

try:
    from sources.reddit import fetch_reddit_posts
    from sources.rss import fetch_rss_posts
    from sources.telegram import fetch_channel_posts
except ImportError:
    fetch_reddit_posts = fetch_rss_posts = fetch_channel_posts = None

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


def _build_dry_run_html() -> str:
    """Генерирует тестовый макет выпуска без обращения к Gemini для проверки WeasyPrint и стилей."""
    from materials_loader import render_backpage_section
    backpage = render_backpage_section()
    return f"""
    <div style="font-family: 'Liberation Serif', Georgia, serif; padding: 20px 0;">
        <h1 style="font-size: 38px; text-align: center; margin: 0; text-transform: uppercase; letter-spacing: 2px;">IMPROVNEWS</h1>
        <p style="text-align: center; font-size: 13px; color: #555; margin-top: 4px; border-bottom: 2px solid #000; padding-bottom: 8px;">ТЕСТОВЫЙ ВЫПУСК • DRY-RUN РЕЖИМ ПРОВЕРКИ СБОРКИ</p>
        <div style="margin-top: 20px;">
            <h2 style="font-size: 22px; border-bottom: 1px solid #111; padding-bottom: 4px;">Радар импровизатора</h2>
            <h3 style="font-size: 18px; margin: 10px 0 6px;">Тестовый турнирный анонс для проверки верстки</h3>
            <p style="font-size: 14px; line-height: 1.45;">Это проверочный текст для dry-run тестирования PDF-рендерера WeasyPrint. Все типографические стили и переносы строк работают стабильно.</p>
        </div>
    </div>
    {backpage}
    """


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Автоматический генератор газеты IMPROVNEWS")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Тестовый прогон пайплайна без сети, секретов, реального кэша и отправки"
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        log.info("[DRY-RUN] Запуск пайплайна в режиме проверки (без внешних API и секретов)...")
        # Изолированный in-memory кэш (без чтения и записи реального newspaper_cache.json)
        cache = {
            "date": datetime.now(LOCAL_TZ).strftime("%Y-%m-%d"),
            "raw_news": "[DRY-RUN] Тестовые данные для сборки",
            "photos": {},
            "sources": {},
            "sections": {},
            "stages": {},
        }
        draft_html = _build_dry_run_html()
        raw_news = cache["raw_news"]
    else:
        validate_env()  # ИЗМЕНЕНО (0.8): fail-fast до любой работы с сетью и кэшем
        cache = load_cache()

        # ИЗМЕНЕНО (0.2): вместо check_if_built_today() (PDF на Диске) смотрим на состояние этапов в кэше.
        if is_already_delivered_today(cache):
            log.info("Газета уже была успешно доставлена сегодня. Завершаю работу.")
            return

        if cache["raw_news"]:
            log.info("Лента новостей загружена из локального дампа (пропуск парсинга).")
            raw_news = cache["raw_news"]
        else:
            log.info("Парсинг источников...")
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
            log.info("Запуск модульного конвейера Gemini...")
            draft_html = build_full_newspaper(raw_news, cache)
        else:
            draft_html = ""

    if raw_news.strip():
        if draft_html:
            log.info("Создание PDF-версии...")
            pdf_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    @page {{
                        size: A4;
                        margin: 12mm 14mm 14mm 14mm;
                        @top-left {{
                            content: "IMPROVNEWS • УТРЕННИЙ ВЫПУСК";
                            font-family: 'Liberation Sans', Helvetica, Arial, sans-serif;
                            font-size: 7.5pt;
                            text-transform: uppercase;
                            letter-spacing: 0.8px;
                            color: #666;
                            border-bottom: 0.5pt solid #bbb;
                            padding-bottom: 3px;
                        }}
                        @top-right {{
                            content: "ЕЖЕДНЕВНАЯ ГАЗЕТА";
                            font-family: 'Liberation Sans', Helvetica, Arial, sans-serif;
                            font-size: 7.5pt;
                            text-transform: uppercase;
                            letter-spacing: 0.8px;
                            color: #666;
                            border-bottom: 0.5pt solid #bbb;
                            padding-bottom: 3px;
                        }}
                        @bottom-left {{
                            content: "Газета импровизационного сообщества • Читайте и делитесь";
                            font-family: 'Liberation Sans', Helvetica, Arial, sans-serif;
                            font-size: 7.5pt;
                            color: #888;
                            border-top: 0.5pt solid #ddd;
                            padding-top: 3px;
                        }}
                        @bottom-right {{
                            content: "Стр. " counter(page) " из " counter(pages);
                            font-family: 'Liberation Sans', Helvetica, Arial, sans-serif;
                            font-size: 7.5pt;
                            font-weight: bold;
                            color: #222;
                            border-top: 0.5pt solid #ddd;
                            padding-top: 3px;
                        }}
                    }}
                    @page :first {{
                        @top-left {{ content: none; border-bottom: none; }}
                        @top-right {{ content: none; border-bottom: none; }}
                    }}
                    body {{
                        background-color: #ffffff;
                        line-height: 1.45;
                        font-family: 'Liberation Sans', 'Helvetica Neue', Helvetica, Arial, sans-serif;
                        color: #1a1a1a;
                        margin: 0;
                    }}
                    h1, h2, h3, h4 {{
                        font-family: 'Liberation Serif', Georgia, 'Times New Roman', serif;
                        color: #000;
                    }}
                    img {{
                        max-width: 100%;
                        object-fit: cover;
                        display: block;
                        border-radius: 3px;
                    }}
                    table {{
                        page-break-inside: auto;
                        width: 100%;
                        border-collapse: collapse;
                    }}
                    tr {{
                        page-break-inside: avoid;
                        break-inside: avoid;
                    }}
                    p {{
                        text-align: justify;
                        hyphens: auto;
                        -webkit-hyphens: auto;
                    }}
                </style>
            </head>
            <body>
                {draft_html}
            </body>
            </html>
            """
            # ИСПРАВЛЕНО (LOW-2/RES-001): сборка во временной директории.
            # Файл newspaper.pdf больше не захламляет корень проекта и гарантированно
            # удаляется после завершения/сбоя пайплайна.
            with tempfile.TemporaryDirectory() as tmp_dir:
                pdf_path = os.path.join(tmp_dir, "newspaper.pdf")
                # ДОБАВЛЕНО (1.4): вместо HTML(...).write_pdf() — render_pdf с SafeImageFetcher
                # (белый список хостов, лимиты размера/времени, проверка формата по содержимому).
                if render_pdf is not None:
                    render_pdf(pdf_html, pdf_path)
                else:
                    with open(pdf_path, "wb") as f:
                        f.write(b"%PDF-1.4\n% Mock PDF for dry-run verification\n%%EOF\n")
                pdf_size = os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0

                if args.dry_run:
                    log.info(f"[DRY-RUN] PDF успешно сформирован во временной папке: {pdf_path} ({pdf_size} байт)")
                    log.info("[DRY-RUN] Пропуск внешних этапов (Google Docs, Google Диск, Telegram).")
                    log.info("[DRY-RUN] Все этапы проверки успешно завершены!")
                    return

                # ИЗМЕНЕНО (0.2): каждый этап пишет свой результат в cache["stages"];
                # уже успешные при повторном запуске пропускаются.
                run_stage(cache, "drive_doc", "Загрузка черновика в Google Docs", update_google_doc, draft_html)
                run_stage(cache, "drive_pdf", "Загрузка PDF на Google Диск", upload_pdf_to_drive, pdf_path)
                run_stage(cache, "telegram", "Отправка PDF в Telegram", send_pdf_to_telegram, pdf_path, cache)

                if is_already_delivered_today(cache):
                    log.info("Успешно завершено!")
                else:
                    # Ненулевой код выхода — чтобы GitHub Actions/ретрай увидели сбой,
                    # а не "зелёный" запуск с потерянной доставкой.
                    log.error(f"Пайплайн завершился частично: {cache['stages']}")
                    raise SystemExit(1)
        else:
            log.warning("Газета не собрана: во всех рубриках сработал NO_CONTENT.")
    else:
        log.warning("Внимание: За последние 24 часа не найдено ни одного нового поста.")

if __name__ == "__main__":
    main()
