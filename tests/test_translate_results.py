import subprocess
import unittest
from unittest.mock import patch


class TranslateResultsTests(unittest.TestCase):
    def test_run_codex_retries_transient_failure(self):
        from idea_scout.translate_results import run_codex

        failure = subprocess.CompletedProcess(
            args=["codex.cmd", "exec", "-"],
            returncode=1,
            stdout="",
            stderr="ERROR: You've hit your usage limit. Try again later.",
        )
        success = subprocess.CompletedProcess(
            args=["codex.cmd", "exec", "-"],
            returncode=0,
            stdout='{"abstract_zh":"translated abstract","idea_core_zh":"translated core"}',
            stderr="",
        )

        with patch("idea_scout.translate_results.subprocess.run", side_effect=[failure, success]) as run_mock:
            with patch("time.sleep"):
                try:
                    result = run_codex("prompt", "codex.cmd exec", 10)
                except RuntimeError as exc:
                    self.fail(f"run_codex did not retry a transient failure: {exc}")

        self.assertEqual("translated abstract", result["abstract_zh"])
        self.assertEqual(2, run_mock.call_count)


if __name__ == "__main__":
    unittest.main()
