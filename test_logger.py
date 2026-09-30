"""Unit-тесты централизованного логгера (logger.py)."""
import io
import sys
import unittest
from logger import get_logger, log


class TestLogger(unittest.TestCase):
    def test_logger_writes_to_dynamic_stdout(self):
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            test_logger = get_logger("test_dynamic")
            test_logger.info("Test message for logger")
        finally:
            sys.stdout = old_stdout

        self.assertIn("Test message for logger", buf.getvalue())

    def test_default_log_instance(self):
        self.assertIsNotNone(log)


if __name__ == "__main__":
    unittest.main()
