"""Unit-тесты конфигурации и источников (CFG-001, LOW-1, LOW-5)."""
import os
import unittest
from config import (
    CHANNELS,
    DEFAULT_HTTP_TIMEOUT,
    DEFAULT_SOURCES_PATH,
    DOC_ID,
    GEMINI_MODEL,
    NO_CONTENT,
    POST_LOOKBACK_HOURS,
    RSS_FEEDS,
    is_empty_section,
    load_sources_config,
    validate_env,
)


class TestConfig(unittest.TestCase):
    def test_sources_config_loaded(self):
        channels, feeds = load_sources_config(DEFAULT_SOURCES_PATH)
        self.assertGreater(len(channels), 50)
        self.assertGreater(len(feeds), 5)
        self.assertTrue("improvmoscow" in channels or "improvru" in channels)
        self.assertTrue(any("connectedcomedy" in f for f in feeds))

    def test_is_empty_section(self):
        self.assertTrue(is_empty_section(None))
        self.assertTrue(is_empty_section(""))
        self.assertTrue(is_empty_section("   "))
        self.assertTrue(is_empty_section("NO_CONTENT"))
        self.assertTrue(is_empty_section("  NO_CONTENT  \n"))
        self.assertFalse(is_empty_section("<div>Новость выпуска</div>"))

    def test_constants(self):
        self.assertEqual(DEFAULT_HTTP_TIMEOUT, 30)
        self.assertEqual(POST_LOOKBACK_HOURS, 24)
        self.assertEqual(GEMINI_MODEL, "gemini-2.5-flash")
        self.assertEqual(DOC_ID, "13tQCDrY7eW1q0kUggi-1wVXpm8Phh8HxuKwu6GREsd8")

    def test_validate_env_missing(self):
        # Без переменных окружения должен вызываться SystemExit
        with self.assertRaises(SystemExit) as cm:
            validate_env()
        self.assertIn("Отсутствуют обязательные переменные окружения", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
