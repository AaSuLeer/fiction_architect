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
        os.environ["SQLITE_PATH"] = str(Path(self.tmp.name) / "web.db")
        os.environ["LLM_MODE"] = "mock"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original)
        self.tmp.cleanup()

    def create_book(self, client: TestClient) -> str:
        response = client.post(
            "/books/create",
            data={
                "title": "页面测试书",
                "premise": "主角在规则压迫下反击",
                "genre": "都市异能",
                "market_channel": "番茄/男频",
                "pov_policy": "third_limited",
                "target_chars_min": "900",
                "target_chars_max": "1800",
            },
            follow_redirects=False,
        )
        self.assertEqual(303, response.status_code)
        return response.headers["location"].split("/")[2]

    def test_pages_return_200(self):
        client = TestClient(app)
        book_id = self.create_book(client)
        paths = [
            "/",
            "/books",
            "/archive",
            f"/books/{book_id}",
            f"/books/{book_id}/setup",
            f"/books/{book_id}/outline",
            f"/books/{book_id}/author",
            f"/books/{book_id}/editor",
            f"/books/{book_id}/chapter-batches/new",
            f"/books/{book_id}/chapters",
            f"/books/{book_id}/continuity",
            f"/books/{book_id}/continuity/atoms",
            f"/books/{book_id}/continuity/drift",
            f"/books/{book_id}/continuity/logs",
            "/resources/authors",
            "/resources/editors",
            "/debug",
            "/exports",
            "/favicon.ico",
        ]
        for path in paths:
            self.assertEqual(200, client.get(path).status_code, path)

    def test_init_demo_route_is_removed(self):
        client = TestClient(app)
        self.assertIn(client.post("/books/init-demo").status_code, {404, 405})

    def test_batch_generation_and_confirm_export_flow(self):
        client = TestClient(app)
        book_id = self.create_book(client)
        response = client.post(f"/books/{book_id}/chapter-batches/new", data={"chapter_count": "1"}, follow_redirects=False)
        self.assertEqual(303, response.status_code)
        batch_id = response.headers["location"].split("/")[-1]
        self.assertEqual(303, client.post(f"/books/{book_id}/chapter-batches/{batch_id}/generate", follow_redirects=False).status_code)
        page = client.get(f"/books/{book_id}/chapters/4")
        self.assertEqual(200, page.status_code)
        self.assertIn("editor_approved".encode("utf-8"), page.content)
        text = "起因是对手逼迫。经过是主角找证据反击。结果是赢下资格但欠下代价。" * 80
        self.assertEqual(303, client.post(f"/books/{book_id}/chapters/4/confirm", data={"body": text}, follow_redirects=False).status_code)
        self.assertEqual(303, client.post(f"/books/{book_id}/exports/docx", follow_redirects=False).status_code)
        continuity = client.get(f"/books/{book_id}/continuity")
        self.assertIn("chapter_memory".encode("utf-8"), continuity.content)

    def test_batch_count_above_twenty_is_rejected(self):
        client = TestClient(app)
        book_id = self.create_book(client)
        response = client.post(f"/books/{book_id}/chapter-batches/new", data={"chapter_count": "21"})
        self.assertEqual(400, response.status_code)
        self.assertIn("最多只能新建 20 章".encode("utf-8"), response.content)


if __name__ == "__main__":
    unittest.main()
