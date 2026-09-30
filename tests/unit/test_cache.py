"""Unit-тесты кэша и стадий выполнения пайплайна (cache.py)."""
import unittest
from datetime import datetime
from config import LOCAL_TZ
from cache import is_already_delivered_today, run_stage, DELIVERY_STAGES


class TestCache(unittest.TestCase):
    def test_is_already_delivered_today_false_when_empty(self):
        cache = {
            "date": datetime.now(LOCAL_TZ).date().isoformat(),
            "stages": {},
        }
        self.assertFalse(is_already_delivered_today(cache))

    def test_is_already_delivered_today_true_when_all_stages_done(self):
        cache = {
            "date": datetime.now(LOCAL_TZ).date().isoformat(),
            "stages": {stage: True for stage in DELIVERY_STAGES},
        }
        self.assertTrue(is_already_delivered_today(cache))

    def test_is_already_delivered_today_false_when_partial(self):
        cache = {
            "date": datetime.now(LOCAL_TZ).date().isoformat(),
            "stages": {"telegram": True},
        }
        self.assertFalse(is_already_delivered_today(cache))

    def test_is_already_delivered_today_false_for_old_date(self):
        cache = {
            "date": "2020-01-01",
            "stages": {stage: True for stage in DELIVERY_STAGES},
        }
        self.assertFalse(is_already_delivered_today(cache))

    def test_run_stage_skips_when_already_done(self):
        cache = {
            "date": datetime.now(LOCAL_TZ).date().isoformat(),
            "stages": {"stage1": True},
        }
        called = []

        def mock_func():
            called.append(True)
            return True

        run_stage(cache, "stage1", "Тестовый этап", mock_func)
        self.assertEqual(len(called), 0)
        self.assertTrue(cache["stages"]["stage1"])

    def test_run_stage_executes_when_not_done(self):
        cache = {
            "date": datetime.now(LOCAL_TZ).date().isoformat(),
            "stages": {},
        }
        called = []

        def mock_func(x):
            called.append(x)
            return True

        run_stage(cache, "stage2", "Новый этап", mock_func, 42)
        self.assertEqual(called, [42])
        self.assertTrue(cache["stages"]["stage2"])


if __name__ == "__main__":
    unittest.main()
