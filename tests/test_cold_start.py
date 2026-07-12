import os
import subprocess
import sys
import unittest
from pathlib import Path


class ColdStartTests(unittest.TestCase):
    def test_import_does_not_load_analysis_stack(self):
        env = os.environ.copy()
        env.update({
            "LINE_CHANNEL_ACCESS_TOKEN": "test",
            "LINE_CHANNEL_SECRET": "test",
            "GEMINI_API_KEY": "test",
            "GCP_PROJECT_ID": "",
            "PYTHONWARNINGS": "ignore",
        })
        script = """
import sys
import app

heavy = (
    "pandas", "numpy", "sklearn", "lightgbm", "google.generativeai",
    "matplotlib", "reportlab", "pypdf",
)
loaded = [name for name in heavy if name in sys.modules]
if loaded:
    raise SystemExit("loaded during startup: " + ", ".join(loaded))
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_import_does_not_make_http_requests(self):
        env = os.environ.copy()
        env.update({
            "LINE_CHANNEL_ACCESS_TOKEN": "test",
            "LINE_CHANNEL_SECRET": "test",
            "GCP_PROJECT_ID": "test-project-123",
            "SUPABASE_URL": "",
            "SUPABASE_KEY": "",
            "PYTHONWARNINGS": "ignore",
        })
        script = """
import requests.sessions

def fail(*args, **kwargs):
    raise RuntimeError("HTTP during import")

requests.sessions.Session.request = fail
import app
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
