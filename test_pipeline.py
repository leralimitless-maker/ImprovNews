"""Интеграционный тест пайплайна в режиме --dry-run (pipeline.py)."""
import io
import os
import sys
import unittest
from pipeline import main


class TestPipelineIntegration(unittest.TestCase):
    def test_pipeline_dry_run(self):
        # Перехватываем вывод stdout
        captured_output = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_output

        try:
            main(["--dry-run"])
        finally:
            sys.stdout = old_stdout

        output = captured_output.getvalue()
        self.assertIn("[DRY-RUN] Запуск пайплайна в режиме проверки", output)
        self.assertIn("Создание PDF-версии...", output)
        self.assertIn("[DRY-RUN] PDF успешно сформирован во временной папке:", output)
        self.assertIn("[DRY-RUN] Все этапы проверки успешно завершены!", output)

        # Проверяем, что в корне проекта не оставлен мусорный файл
        self.assertFalse(os.path.exists("newspaper.pdf"))


if __name__ == "__main__":
    unittest.main()
