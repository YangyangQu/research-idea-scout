import unittest
from unittest.mock import patch


class CodexIdeaScoreTests(unittest.TestCase):
    def test_run_codex_uses_utf8_for_prompt_io(self):
        from idea_scout.codex_idea_score import run_codex

        captured = {}

        class Result:
            returncode = 0
            stdout = "{}"
            stderr = ""

        def fake_run(cmd, **kwargs):
            captured.update(kwargs)
            return Result()

        with patch("idea_scout.codex_idea_score.subprocess.run", fake_run):
            rc, stdout, stderr = run_codex("degree symbol 360° and curly quote ’", "codex.cmd exec", 10)

        self.assertEqual(0, rc)
        self.assertEqual("utf-8", captured["encoding"])
        self.assertEqual("replace", captured["errors"])
        self.assertTrue(captured["text"])


if __name__ == "__main__":
    unittest.main()
