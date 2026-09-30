"""Unit-тесты фетчеров и алгоритмов дедупликации источников."""
import unittest
from datetime import datetime
from config import LOCAL_TZ, TG_MAX_WORKERS
from sources.telegram import _dedup_key, _fetch_single_channel
from sources.rss import _domain_label
from sources.reddit import _format_unix_local


class TestSources(unittest.TestCase):
    def test_tg_max_workers_constant(self):
        self.assertIsInstance(TG_MAX_WORKERS, int)
        self.assertGreaterEqual(TG_MAX_WORKERS, 1)
        self.assertLessEqual(TG_MAX_WORKERS, 10)

    def test_fetch_single_channel_graceful(self):
        # Должен возвращать пустой список при недоступности/ошибке без исключений
        res = _fetch_single_channel("nonexistent_channel_test_404", datetime.now(LOCAL_TZ), {})
        self.assertIsInstance(res, list)
    def test_dedup_key_identical_for_reposts_with_different_links(self):
        text1 = "Большой импровизационный джем в пятницу вечером! Регистрация тут: https://example.com/link1"
        text2 = "Большой импровизационный джем в пятницу вечером! Регистрация тут: https://other-link.ru/utm=123"
        key1 = _dedup_key(text1)
        key2 = _dedup_key(text2)
        self.assertNotEqual(key1, "")
        self.assertEqual(key1, key2)

    def test_dedup_key_empty_for_too_short_text(self):
        self.assertEqual(_dedup_key("🔥"), "")
        self.assertEqual(_dedup_key("Короткий текст"), "")

    def test_domain_label(self):
        self.assertEqual(_domain_label("https://www.connectedcomedy.com/feed/"), "connectedcomedy.com")
        self.assertEqual(_domain_label("https://improveverywhere.com/feed"), "improveverywhere.com")
        self.assertEqual(_domain_label("invalid-url"), "Блог")

    def test_format_unix_local(self):
        res = _format_unix_local(1700000000)
        self.assertEqual(len(res), 5)
        self.assertIn(".", res)
        self.assertEqual(_format_unix_local(None), "")
        self.assertEqual(_format_unix_local("invalid"), "")

    def test_fetch_reddit_posts_fallback_graceful(self):
        # При отсутствии сети или некорректных данных функция не должна падать
        import itertools
        from sources.reddit import fetch_reddit_posts
        text, sources = fetch_reddit_posts(itertools.count(1))
        self.assertIsInstance(text, str)
        self.assertIsInstance(sources, dict)


if __name__ == "__main__":
    unittest.main()
