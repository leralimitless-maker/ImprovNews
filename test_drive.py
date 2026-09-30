"""Unit-тесты модуля публикации в Google Drive (publishing/drive.py)."""
import os
import unittest
from publishing.drive import update_google_doc, upload_pdf_to_drive


class TestDrivePublishing(unittest.TestCase):
    def test_update_google_doc_no_credentials_leaves_no_files(self):
        # При отсутствии GOOGLE_CREDENTIALS функция должна вернуть False
        # и ни в коем случае не оставить draft.html в корне проекта
        result = update_google_doc("<html><body>Черновик выпуска</body></html>")
        self.assertFalse(result)
        self.assertFalse(os.path.exists("draft.html"))

    def test_upload_pdf_to_drive_no_credentials(self):
        result = upload_pdf_to_drive("/tmp/mock_newspaper.pdf")
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
