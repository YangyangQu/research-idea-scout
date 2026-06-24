import tempfile
import unittest
from pathlib import Path

from idea_scout.profile import load_profile


class FullPipelineTests(unittest.TestCase):
    def test_profile_loads_topic_anchors(self):
        yaml_text = """
name: agent_memory
language: English
description: LLM agent memory research.
target_tasks:
  - Find reusable memory mechanisms.
prefer:
  - Explicit memory retrieval.
downweight:
  - Generic chatbot applications.
positive_keywords:
  - agent memory
negative_keywords:
  - survey
topic_anchors:
  high_value:
    - episodic memory
    - memory retrieval
  required_any:
    - agent memory
  broad_ai:
    - large language model
  off_topic_domains:
    - database indexing
scoring_dimensions:
  - key: fit
    description: Fit to agent memory.
    weight: 1.0
"""

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.yaml"
            path.write_text(yaml_text, encoding="utf-8")
            profile = load_profile(path)

        self.assertEqual(["episodic memory", "memory retrieval"], profile.topic_anchors["high_value"])
        self.assertEqual(["agent memory"], profile.topic_anchors["required_any"])

    def test_extract_profile_yaml_from_markdown_and_loads_profile(self):
        from idea_scout.full_pipeline import extract_profile_yaml

        text = """
Here is the generated profile:

```yaml
name: streaming_assistance
language: English
description: >
  Find papers for streaming procedural assistants.
target_tasks:
  - Decide when an assistant should proactively intervene.
prefer:
  - Online task monitoring.
downweight:
  - Dataset-only papers.
positive_keywords:
  - proactive assistance
  - intervention timing
negative_keywords:
  - survey
scoring_dimensions:
  - key: intervention_timing
    description: Whether the paper helps intervention timing.
    weight: 2.0
```
"""

        yaml_text = extract_profile_yaml(text)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.yaml"
            path.write_text(yaml_text, encoding="utf-8")
            profile = load_profile(path)

        self.assertEqual("streaming_assistance", profile.name)
        self.assertEqual(["intervention_timing"], [d.key for d in profile.scoring_dimensions])

    def test_fallback_profile_from_description_is_valid_and_query_friendly(self):
        from idea_scout.full_pipeline import fallback_profile_yaml

        yaml_text = fallback_profile_yaml(
            "I care about AI streaming egocentric proactive assistants, especially intervention timing and recovery."
        )

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fallback.yaml"
            path.write_text(yaml_text, encoding="utf-8")
            profile = load_profile(path)

        self.assertTrue(profile.name.startswith("generated_ai_profile_"))
        self.assertGreaterEqual(len(profile.positive_keywords), 8)
        self.assertGreaterEqual(len(profile.scoring_dimensions), 5)
        self.assertIn("intervention timing", profile.positive_keywords)

    def test_run_full_pipeline_translates_before_portal_import(self):
        from idea_scout.full_pipeline import FullPipelineOptions, run_full_pipeline

        commands = []

        def fake_runner(cmd, cwd):
            commands.append(cmd)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            options = FullPipelineOptions(
                description="streaming egocentric proactive assistant",
                profile_llm=False,
                preset="frugal",
                sources=("openalex", "arxiv"),
                score=True,
                translate=True,
                import_portal=True,
                codex_cmd="codex.cmd exec",
                timeout=123,
                max_retries=4,
            )

            manifest = run_full_pipeline(options, root=root, runner=fake_runner)

        self.assertEqual(3, len(commands))
        self.assertIn("scripts/auto_scout.py", commands[0])
        self.assertIn("--score", commands[0])
        self.assertNotIn("--import-portal", commands[0])
        self.assertIn("scripts/translate_results.py", commands[1])
        self.assertEqual("4", commands[1][commands[1].index("--max-retries") + 1])
        self.assertIn("web/import_jsonl.py", commands[2])
        self.assertEqual(str(manifest["paths"]["bilingual_scores"]), commands[2][commands[2].index("--input") + 1])

    def test_run_full_pipeline_imports_scores_during_auto_when_not_translating(self):
        from idea_scout.full_pipeline import FullPipelineOptions, run_full_pipeline

        commands = []

        def fake_runner(cmd, cwd):
            commands.append(cmd)

        with tempfile.TemporaryDirectory() as td:
            options = FullPipelineOptions(
                description="streaming egocentric proactive assistant",
                profile_llm=False,
                score=True,
                translate=False,
                import_portal=True,
            )

            run_full_pipeline(options, root=Path(td), runner=fake_runner)

        self.assertEqual(1, len(commands))
        self.assertIn("scripts/auto_scout.py", commands[0])
        self.assertIn("--import-portal", commands[0])

    def test_dynamic_anchors_can_be_disabled_for_auto_scout(self):
        from idea_scout.full_pipeline import FullPipelineOptions, run_full_pipeline

        commands = []

        def fake_runner(cmd, cwd):
            commands.append(cmd)

        with tempfile.TemporaryDirectory() as td:
            options = FullPipelineOptions(
                description="llm agent memory",
                profile_llm=False,
                score=False,
                dry_run=False,
                dynamic_anchors=False,
            )

            run_full_pipeline(options, root=Path(td), runner=fake_runner)

        self.assertEqual(1, len(commands))
        self.assertIn("--no-profile-anchors", commands[0])

    def test_translate_or_portal_import_requires_scoring(self):
        from idea_scout.full_pipeline import FullPipelineOptions, run_full_pipeline

        invalid_options = [
            FullPipelineOptions(description="assistant", score=False, translate=True),
            FullPipelineOptions(description="assistant", score=False, import_portal=True),
        ]

        for options in invalid_options:
            with self.subTest(options=options):
                with tempfile.TemporaryDirectory() as td:
                    with self.assertRaises(ValueError):
                        run_full_pipeline(options, root=Path(td))


if __name__ == "__main__":
    unittest.main()
