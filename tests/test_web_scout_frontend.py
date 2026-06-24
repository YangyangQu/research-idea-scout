import time
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import web.app.main as portal


class WebScoutFrontendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.old_pipeline_root = getattr(portal, "SCOUT_PIPELINE_ROOT", None)
        self.old_job_dir = getattr(portal, "SCOUT_JOB_DIR", None)
        if hasattr(portal, "SCOUT_JOBS"):
            portal.SCOUT_JOBS.clear()
        portal.SCOUT_PIPELINE_ROOT = self.root
        portal.SCOUT_JOB_DIR = self.root / "logs" / "scout_jobs"
        self.client = TestClient(portal.app)

    def tearDown(self):
        self.client.close()
        if self.old_pipeline_root is not None:
            portal.SCOUT_PIPELINE_ROOT = self.old_pipeline_root
        if self.old_job_dir is not None:
            portal.SCOUT_JOB_DIR = self.old_job_dir
        if hasattr(portal, "SCOUT_JOBS"):
            portal.SCOUT_JOBS.clear()
        self.tmp.cleanup()

    def test_scout_page_renders_form_and_navigation(self):
        response = self.client.get("/scout?lang=zh")

        self.assertEqual(200, response.status_code)
        self.assertIn('id="scout-form"', response.text)
        self.assertIn('name="description"', response.text)
        self.assertIn('name="profile_llm"', response.text)
        self.assertIn('name="dynamic_anchors"', response.text)

    def test_scout_api_runs_dry_run_job_and_returns_manifest(self):
        response = self.client.post(
            "/api/scout/jobs",
            json={
                "description": "streaming egocentric proactive assistant",
                "profile_llm": False,
                "dynamic_anchors": False,
                "score": False,
                "dry_run": True,
                "preset": "frugal",
                "sources": ["openalex", "arxiv"],
            },
        )

        self.assertEqual(200, response.status_code)
        job_id = response.json()["job_id"]

        status = {}
        for _ in range(30):
            status = self.client.get(f"/api/scout/jobs/{job_id}").json()
            if status["status"] in {"done", "failed"}:
                break
            time.sleep(0.1)

        self.assertEqual("done", status["status"])
        self.assertTrue(status["manifest"]["dry_run"])
        self.assertFalse(status["manifest"]["dynamic_anchors"])
        self.assertEqual("fallback", status["manifest"]["profile_source"])
        self.assertIn("profile", status["manifest"]["paths"])
        self.assertIn("Job finished", status["log_tail"])


if __name__ == "__main__":
    unittest.main()
