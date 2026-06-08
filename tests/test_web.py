from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


class WebSmokeTests(unittest.TestCase):
    def setUp(self):
        self.original = os.environ.copy()
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DB_BACKEND"] = "sqlite"
        os.environ["SQLITE_PATH"] = str(Path(self.tmp.name) / "web_test.db")
        os.environ["LLM_MODE"] = "mock"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original)
        self.tmp.cleanup()

    def test_pages_return_200(self):
        client = TestClient(app)
        self.assertEqual(200, client.get("/").status_code)
        self.assertEqual(200, client.get("/favicon.ico").status_code)
        response = client.post("/books/init-demo", follow_redirects=False)
        self.assertEqual(303, response.status_code)
        self.assertEqual(200, client.get("/books").status_code)
        self.assertEqual(200, client.get("/books/1").status_code)
        self.assertEqual(200, client.get("/books/1/chapters/1").status_code)
        self.assertEqual(200, client.get("/departments/author").status_code)
        self.assertEqual(200, client.get("/departments/continuity").status_code)
        self.assertEqual(200, client.get("/departments/writing").status_code)
        self.assertEqual(200, client.get("/departments/editorial").status_code)
        self.assertEqual(200, client.get("/debug").status_code)

    def test_create_formal_book_from_web(self):
        client = TestClient(app)
        response = client.post("/books/create", data={"title": "正式项目", "premise": "主角在规则压迫下反击。"}, follow_redirects=False)
        self.assertEqual(303, response.status_code)
        page = client.get("/books/1")
        self.assertEqual(200, page.status_code)
        self.assertIn("文风与生产控制".encode("utf-8"), page.content)

    def test_run_chapter_from_web(self):
        client = TestClient(app)
        client.post("/books/init-demo", follow_redirects=False)
        response = client.post("/books/1/chapters/1/run", follow_redirects=False)
        self.assertEqual(303, response.status_code)
        page = client.get("/books/1/chapters/1")
        self.assertEqual(200, page.status_code)
        self.assertIn("正文".encode("utf-8"), page.content)


if __name__ == "__main__":
    unittest.main()
