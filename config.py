"""Конфигурация: секреты из окружения (Pydantic-Settings), ID документов Google, списки источников, лимиты текста.
Модуль-лист: ничего не импортирует из проекта."""
import json
import os
from datetime import timedelta, timezone

LOCAL_TZ = timezone(timedelta(hours=5))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "newspaper_cache.json")
DEFAULT_SOURCES_PATH = os.path.join(BASE_DIR, "sources.json")


def load_sources_config(sources_path: str = DEFAULT_SOURCES_PATH) -> tuple[list[str], list[str]]:
    """Загружает списки каналов Telegram и RSS-фидов из внешнего JSON/YAML конфига (CFG-001)."""
    if os.path.exists(sources_path):
        try:
            with open(sources_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                channels = data.get("channels") or []
                rss_feeds = data.get("rss_feeds") or []
                return channels, rss_feeds
        except Exception as e:
            print(f"[!] Предупреждение: не удалось прочитать {sources_path}: {e}", flush=True)
    return [], []


try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from pydantic import Field

    class Settings(BaseSettings):
        bot_token: str = Field(default="", validation_alias="BOT_TOKEN")
        gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
        my_chat_id: str = Field(default="", validation_alias="MY_CHAT_ID")
        google_credentials: str = Field(default="", validation_alias="GOOGLE_CREDENTIALS")

        doc_id: str = Field(default="13tQCDrY7eW1q0kUggi-1wVXpm8Phh8HxuKwu6GREsd8", validation_alias="DOC_ID")
        pdf_folder_id: str = Field(default="1enu9CNlCXxGMojV6lbtjobHWWrhg8q_c", validation_alias="PDF_FOLDER_ID")

        gemini_model: str = Field(default="gemini-2.5-flash", validation_alias="GEMINI_MODEL")

        tg_text_budget: int = Field(default=25000, validation_alias="TG_TEXT_BUDGET")
        rss_text_budget: int = Field(default=8000, validation_alias="RSS_TEXT_BUDGET")
        reddit_text_budget: int = Field(default=4000, validation_alias="REDDIT_TEXT_BUDGET")

        sources_file: str = Field(default=DEFAULT_SOURCES_PATH, validation_alias="SOURCES_FILE")

        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )

        def validate_secrets(self) -> None:
            missing = []
            if not (self.bot_token or "").strip():
                missing.append("BOT_TOKEN")
            if not (self.gemini_api_key or "").strip():
                missing.append("GEMINI_API_KEY")
            if not (self.my_chat_id or "").strip():
                missing.append("MY_CHAT_ID")
            if missing:
                raise SystemExit(f"Отсутствуют обязательные переменные окружения: {', '.join(missing)}")

    settings = Settings()

except ImportError:
    class Settings:  # type: ignore
        """Fallback-реализация настроек при запуске без pydantic-settings."""
        def __init__(self):
            self.bot_token = os.environ.get("BOT_TOKEN", "")
            self.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
            self.my_chat_id = os.environ.get("MY_CHAT_ID", "")
            self.google_credentials = os.environ.get("GOOGLE_CREDENTIALS", "")
            self.doc_id = os.environ.get("DOC_ID", "13tQCDrY7eW1q0kUggi-1wVXpm8Phh8HxuKwu6GREsd8")
            self.pdf_folder_id = os.environ.get("PDF_FOLDER_ID", "1enu9CNlCXxGMojV6lbtjobHWWrhg8q_c")
            self.gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
            self.tg_text_budget = int(os.environ.get("TG_TEXT_BUDGET", "25000"))
            self.rss_text_budget = int(os.environ.get("RSS_TEXT_BUDGET", "8000"))
            self.reddit_text_budget = int(os.environ.get("REDDIT_TEXT_BUDGET", "4000"))
            self.sources_file = os.environ.get("SOURCES_FILE", DEFAULT_SOURCES_PATH)

        def validate_secrets(self) -> None:
            missing = []
            if not (self.bot_token or "").strip():
                missing.append("BOT_TOKEN")
            if not (self.gemini_api_key or "").strip():
                missing.append("GEMINI_API_KEY")
            if not (self.my_chat_id or "").strip():
                missing.append("MY_CHAT_ID")
            if missing:
                raise SystemExit(f"Отсутствуют обязательные переменные окружения: {', '.join(missing)}")

    settings = Settings()


def validate_env() -> None:
    settings.validate_secrets()


# Загрузка источников из внешнего конфига sources.json (CFG-001)
_channels_from_file, _feeds_from_file = load_sources_config(settings.sources_file)

CHANNELS = _channels_from_file
RSS_FEEDS = _feeds_from_file

# Обратная совместимость для модулей, импортирующих переменные напрямую:
BOT_TOKEN = settings.bot_token
GEMINI_API_KEY = settings.gemini_api_key
MY_CHAT_ID = settings.my_chat_id
REQUIRED_ENV = ("BOT_TOKEN", "GEMINI_API_KEY", "MY_CHAT_ID")

DOC_ID = settings.doc_id
PDF_FOLDER_ID = settings.pdf_folder_id

TG_TEXT_BUDGET = settings.tg_text_budget
RSS_TEXT_BUDGET = settings.rss_text_budget
REDDIT_TEXT_BUDGET = settings.reddit_text_budget

GEMINI_MODEL = settings.gemini_model

# Константы таймаутов, периодов выборки и маркеров (LOW-1, LOW-5)
DEFAULT_HTTP_TIMEOUT: int = 30
RSS_HTTP_TIMEOUT: int = 20
POST_LOOKBACK_HOURS: int = 24
DEFAULT_USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ImprovNewspaperBot/1.0"
TG_MAX_WORKERS: int = 5

NO_CONTENT: str = "NO_CONTENT"


def is_empty_section(section_html: str | None) -> bool:
    """Точная проверка: раздел пуст или содержит маркер отсутствия контента (LOW-5)."""
    if not section_html:
        return True
    return section_html.strip() == NO_CONTENT or not section_html.strip()

