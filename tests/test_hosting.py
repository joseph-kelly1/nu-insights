"""Production frontend routing must preserve API and asset behavior."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import advisor


class HostingTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        (root / "index.html").write_text("<html>NU Insights</html>")
        (root / "manifest.json").write_text('{"name":"NU Insights"}')
        patcher = patch.object(advisor, "FRONTEND_DIR", root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = advisor.app.test_client()

    def test_root_and_client_route_serve_frontend(self):
        for path in ("/", "/planner/semester"):
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"NU Insights", response.data)
                self.assertIn("max-age=0", response.headers["Cache-Control"])

    def test_public_files_are_served(self):
        with self.client.get("/manifest.json") as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, {"name": "NU Insights"})

    def test_unknown_api_missing_assets_and_traversal_do_not_serve_frontend(self):
        for path in ("/api", "/api/unknown", "/static/missing.js", "/missing.png", "/../requirements.txt"):
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 404, path)
                self.assertNotIn(b"NU Insights", response.data)

    def test_existing_api_still_returns_json(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "ok")
