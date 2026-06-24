import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import web.app.main as portal
from web.import_jsonl import import_rows


class WebPortalBilingualTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        self.db_path = root / "portal.db"
        self.jsonl_path = root / "scores.jsonl"
        row = {
            "title": "Proactive Assistant Dialogue Generation from Streaming Egocentric Videos",
            "abstract": "A streaming egocentric assistant decides when and how to speak.",
            "abstract_zh": "一种流式第一视角助手，用于判断何时以及如何主动发声。",
            "venue": "arXiv",
            "year": 2025,
            "url": "https://example.test/paper",
            "authors": ["A. Researcher"],
            "priority": "keep",
            "profile_name": "proassist_procedural_assistance",
            "idea_core": "Models proactive dialogue from streaming egocentric context.",
            "idea_core_zh": "从流式第一视角上下文中建模主动对话。",
            "transferable_mechanism": "Turns visual task state into speak/silence and response decisions.",
            "transferable_mechanism_zh": "把视觉任务状态转成说话、沉默和响应决策。",
            "fit_reason": "Directly matches proactive procedural assistance.",
            "fit_reason_zh": "直接匹配主动式流程辅助。",
            "risk_or_limitation": "Needs stronger recovery evaluation.",
            "risk_or_limitation_zh": "仍需要更强的恢复效果评估。",
            "rank_score": 8.1,
            "score_overall_fit": 8.0,
            "score_theory_novelty": 6.0,
            "scores": {"intervention_timing_value": 8.0},
        }
        self.jsonl_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        import_rows(self.jsonl_path, self.db_path)
        self.old_db = portal.DB_PATH
        portal.DB_PATH = self.db_path
        self.client = TestClient(portal.app)

    def tearDown(self):
        portal.DB_PATH = self.old_db
        self.client.close()
        self.tmp.cleanup()

    def test_chinese_mode_localizes_ui_and_content_but_keeps_title_original(self):
        detail = self.client.get("/articles/1?lang=zh")
        self.assertEqual(200, detail.status_code)
        self.assertIn("IdeaScout 研究雷达", detail.text)
        self.assertIn("Proactive Assistant Dialogue Generation", detail.text)
        self.assertIn("一种流式第一视角助手", detail.text)
        self.assertIn("把视觉任务状态转成", detail.text)
        self.assertIn("综合分", detail.text)

    def test_english_mode_uses_original_content_and_english_ui(self):
        detail = self.client.get("/articles/1?lang=en")
        self.assertEqual(200, detail.status_code)
        self.assertIn("IdeaScout Research Radar", detail.text)
        self.assertIn("A streaming egocentric assistant decides", detail.text)
        self.assertIn("Turns visual task state", detail.text)
        self.assertIn("Rank score", detail.text)
        self.assertNotIn("一种流式第一视角助手", detail.text)

    def test_article_list_has_language_switch(self):
        articles = self.client.get("/articles?lang=zh")
        self.assertEqual(200, articles.status_code)
        self.assertIn("English", articles.text)
        self.assertIn("论文库", articles.text)


if __name__ == "__main__":
    unittest.main()
