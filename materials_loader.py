"""Загрузка и форматирование материалов: цитаты, упражнения и словарь для газеты."""
import json
import os
from datetime import datetime
from html import escape as _e

from config import LOCAL_TZ

MATERIALS_DIR = os.path.join(os.path.dirname(__file__), "materials")


def _load_json(filename: str, default: list) -> list:
    path = os.path.join(MATERIALS_DIR, filename)
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else default
    except Exception as e:
        print(f"[!] Не удалось прочитать {filename}: {e}", flush=True)
        return default


def get_today_materials() -> dict:
    """Выбирает материалы на сегодняшний выпуск по номеру дня в году."""
    day_idx = datetime.now(LOCAL_TZ).timetuple().tm_yday
    quotes = _load_json("quotes.json", [])
    exercises = _load_json("exercises.json", [])
    terms = _load_json("terms.json", [])

    quote = quotes[day_idx % len(quotes)] if quotes else {
        "quote": "В импровизации нет ошибок — есть только новые вводные.",
        "author": "Кит Джонстон",
        "source": "«Импровизация и театр»"
    }
    secondary_quote = quotes[(day_idx + 3) % len(quotes)] if quotes else quote
    exercise = exercises[day_idx % len(exercises)] if exercises else None
    term = terms[day_idx % len(terms)] if terms else None

    return {
        "quote": quote,
        "secondary_quote": secondary_quote,
        "exercise": exercise,
        "term": term,
    }


def render_quote_filler(quote_dict: dict = None) -> str:
    """Подвальный наполнитель (лента-афоризм) для закрытия пустот внизу полос."""
    if not quote_dict:
        mats = get_today_materials()
        quote_dict = mats.get("quote")
    if not quote_dict:
        return ""

    quote_text = _e(quote_dict.get("quote", ""))
    author = _e(quote_dict.get("author", ""))
    source = _e(quote_dict.get("source", ""))
    source_html = f" <span style=\"color: #666; font-size: 8.5pt;\">({source})</span>" if source else ""

    return f"""
    <div style="margin-top: 14px; border-top: 2px solid #111; border-bottom: 1px solid #111; padding: 7px 10px; background-color: #fafafa; break-inside: avoid; page-break-inside: avoid;">
        <table width="100%" border="0" cellpadding="0" cellspacing="0" style="border-collapse: collapse;">
            <tr>
                <td width="20%" style="vertical-align: middle; border-right: 1px solid #111; padding-right: 10px;">
                    <span style="font-family: 'Liberation Sans', Helvetica, Arial, sans-serif; font-size: 7.5pt; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; color: #000; display: block;">МЫСЛЬ НОМЕРА</span>
                    <span style="font-family: 'Liberation Serif', Georgia, serif; font-size: 8.5pt; font-style: italic; color: #444; display: block; margin-top: 2px;">{author}</span>
                </td>
                <td width="80%" style="vertical-align: middle; padding-left: 12px;">
                    <p style="font-family: 'Liberation Serif', Georgia, 'Times New Roman', serif; font-size: 9.5pt; font-style: italic; margin: 0; line-height: 1.35; color: #111;">«{quote_text}»{source_html}</p>
                </td>
            </tr>
        </table>
    </div>
    """


def render_backpage_section() -> str:
    """Формирует финальную образовательную полосу А4 («Мастерская и Практикум»)."""
    mats = get_today_materials()
    ex = mats.get("exercise")
    term = mats.get("term")
    quote = mats.get("secondary_quote") or mats.get("quote")

    if not ex:
        return ""

    title = _e(ex.get("title", "Упражнение дня"))
    category = _e(ex.get("category", "Практика"))
    focus = _e(ex.get("focus", ""))
    desc = _e(ex.get("description", ""))
    advice = _e(ex.get("advice", ""))

    term_html = ""
    if term:
        term_word = _e(term.get("term", ""))
        term_def = _e(term.get("definition", ""))
        term_cat = _e(term.get("category", "")).upper()
        header_text = f"СЛОВАРЬ ИМПРОВИЗАТОРА • {term_cat}" if term_cat else "СЛОВАРЬ ИМПРОВИЗАТОРА • ОПРЕДЕЛЕНИЕ ДНЯ"
        term_html = f"""
        <div style="margin-top: 14px; padding: 12px 14px; background-color: #f7f7f7; border-left: 3px solid #111; border-radius: 2px;">
            <span style="font-family: 'Liberation Sans', sans-serif; font-size: 8pt; font-weight: bold; text-transform: uppercase; letter-spacing: 0.8px; color: #666; display: block; margin-bottom: 3px;">{header_text}</span>
            <strong style="font-family: 'Liberation Serif', Georgia, serif; font-size: 13pt; color: #000; display: block; margin-bottom: 4px;">{term_word}</strong>
            <p style="font-family: 'Liberation Sans', sans-serif; font-size: 9.5pt; line-height: 1.45; margin: 0; color: #222; text-align: justify;">{term_def}</p>
        </div>
        """

    quote_html = ""
    if quote:
        q_author = _e(quote.get("author", ""))
        q_text = _e(quote.get("quote", ""))
        q_src = _e(quote.get("source", ""))
        quote_html = f"""
        <div style="margin-top: 14px; padding: 14px; background-color: #111111; color: #ffffff; border-radius: 3px;">
            <span style="font-family: 'Liberation Sans', sans-serif; font-size: 8pt; font-weight: bold; text-transform: uppercase; letter-spacing: 1px; color: #aaa; display: block; margin-bottom: 6px;">ПРИНЦИП МАСТЕРА • {q_author}</span>
            <p style="font-family: 'Liberation Serif', Georgia, serif; font-style: italic; font-size: 11pt; line-height: 1.4; margin: 0 0 6px 0; color: #fff;">«{q_text}»</p>
            <span style="font-family: 'Liberation Sans', sans-serif; font-size: 8pt; color: #888; display: block;">Источник: {q_src}</span>
        </div>
        """

    return f"""
    <div style="page-break-before: always; break-before: page; margin-top: 10px;">
        <div style="border-top: 3px double #111; border-bottom: 2px solid #111; padding: 4px 0; margin-bottom: 14px;">
            <table width="100%" border="0" cellpadding="0" cellspacing="0">
                <tr>
                    <td style="font-family: 'Liberation Serif', Georgia, serif; font-size: 18pt; font-weight: 900; text-transform: uppercase; letter-spacing: 1px; color: #000;">
                        МАСТЕРСКАЯ И ПРАКТИКУМ
                    </td>
                    <td style="text-align: right; font-family: 'Liberation Sans', sans-serif; font-size: 8pt; text-transform: uppercase; letter-spacing: 0.8px; color: #666; font-weight: bold;">
                        МЕТОДИЧЕСКАЯ ПОЛОСА • ДЛЯ ТРЕНЕРОВ И АКТЁРОВ
                    </td>
                </tr>
            </table>
        </div>

        <div style="margin-bottom: 14px;">
            <table width="100%" border="0" cellpadding="0" cellspacing="0" style="margin-bottom: 6px;">
                <tr>
                    <td>
                        <span style="display: inline-block; background-color: #111; color: #fff; font-family: 'Liberation Sans', sans-serif; font-size: 7.5pt; font-weight: bold; padding: 2px 7px; text-transform: uppercase; letter-spacing: 0.8px; border-radius: 2px;">{category}</span>
                    </td>
                    <td style="text-align: right; font-family: 'Liberation Sans', sans-serif; font-size: 8.5pt; color: #555; font-style: italic;">
                        Фокус: {focus}
                    </td>
                </tr>
            </table>
            <h3 style="font-family: 'Liberation Serif', Georgia, 'Times New Roman', serif; font-size: 18pt; font-weight: 700; margin: 0 0 10px 0; color: #000; line-height: 1.2;">{title}</h3>
            <p style="font-family: 'Liberation Sans', sans-serif; font-size: 10pt; line-height: 1.5; margin: 0 0 10px 0; text-align: justify; color: #1a1a1a;">{desc}</p>
            <div style="padding: 10px 12px; background-color: #f9f9f9; border-left: 2px solid #555; margin-top: 8px;">
                <strong style="font-family: 'Liberation Sans', sans-serif; font-size: 8.5pt; text-transform: uppercase; color: #333; display: block; margin-bottom: 3px;">Совет тренера:</strong>
                <p style="font-family: 'Liberation Sans', sans-serif; font-size: 9pt; line-height: 1.45; margin: 0; color: #444; text-align: justify;">{advice}</p>
            </div>
        </div>

        <table width="100%" border="0" cellpadding="0" cellspacing="0" style="margin-top: 14px; border-top: 1px solid #111; padding-top: 12px;">
            <tr>
                <td width="50%" style="vertical-align: top; padding-right: 12px;">
                    {term_html}
                </td>
                <td width="50%" style="vertical-align: top; padding-left: 12px;">
                    {quote_html}
                </td>
            </tr>
        </table>

        <div style="margin-top: 18px; border-top: 1px solid #111; padding-top: 10px; text-align: center;">
            <p style="font-family: 'Liberation Sans', sans-serif; font-size: 8pt; text-transform: uppercase; letter-spacing: 1px; color: #777; margin: 0;">
                IMPROVNEWS • БИБЛИОТЕКА ЗНАНИЙ • МАТЕРИАЛЫ ДЛЯ ПРАКТИКИ И РАЗВИТИЯ КОМАНДЫ
            </p>
        </div>
    </div>
    """
