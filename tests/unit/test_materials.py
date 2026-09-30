"""Unit-тесты загрузчика методических материалов (materials_loader.py)."""
import unittest
from materials_loader import (
    get_today_materials,
    render_backpage_section,
    render_quote_filler,
)


class TestMaterials(unittest.TestCase):
    def test_get_today_materials(self):
        m = get_today_materials()
        self.assertIn("exercise", m)
        self.assertIn("term", m)
        self.assertIn("quote", m)
        self.assertIn("secondary_quote", m)

        self.assertIn("title", m["exercise"])
        self.assertIn("term", m["term"])
        self.assertIn("author", m["quote"])

    def test_render_backpage_section(self):
        html = render_backpage_section()
        self.assertIn("МАСТЕРСКАЯ И ПРАКТИКУМ", html)
        self.assertIn("СЛОВАРЬ ИМПРОВИЗАТОРА", html)
        self.assertIn("ПРИНЦИП МАСТЕРА", html)

    def test_render_quote_filler(self):
        quote_html = render_quote_filler()
        self.assertIn("background-color: #fafafa", quote_html)
        self.assertIn("«", quote_html)


if __name__ == "__main__":
    unittest.main()
