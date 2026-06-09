from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.storage import Database, Repository, initialize_database
from app.storage.repository import json_safe


class IsolatedEnv:
    def __init__(self):
        self.original = os.environ.copy()
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "chapter_repair.db"

    def __enter__(self):
        os.environ.clear()
        os.environ.update(self.original)
        os.environ["DB_BACKEND"] = "sqlite"
        os.environ["SQLITE_PATH"] = str(self.db_path)
        os.environ["LLM_MODE"] = "mock"
        return self

    def __exit__(self, exc_type, exc, tb):
        os.environ.clear()
        os.environ.update(self.original)
        self.tmp.cleanup()


class ChapterRepairTests(unittest.TestCase):
    def repo(self) -> Repository:
        settings = get_settings()
        db = Database(settings)
        initialize_database(db)
        return Repository(db)

    def test_batch_reuses_unwritten_existing_plans_before_appending(self):
        with IsolatedEnv():
            repo = self.repo()
            book_id = repo.create_book("reuse-slots", "test")
            first_batch = repo.create_chapter_batch(book_id, 3)
            repo.update_chapter_plan(book_id, 1, "custom-title", "custom-goal", "", "", "", "custom-summary", 1600)
            second_batch = repo.create_chapter_batch(book_id, 2)
            self.assertNotEqual(first_batch, second_batch)
            plans = repo.list_chapter_plan_rows(book_id, second_batch)
            self.assertEqual([1, 2], [row["chapter_no"] for row in plans])
            self.assertEqual("custom-title", plans[0]["title"])
            self.assertEqual("custom-summary", plans[0]["plot_summary"])

    def test_delete_chapter_keeps_number_gap_for_regeneration(self):
        with IsolatedEnv():
            repo = self.repo()
            book_id = repo.create_book("delete-gap", "test")
            repo.create_chapter_batch(book_id, 3)
            for no in [1, 2, 3]:
                repo.save_chapter_body(book_id, no, f"chapter {no}", "body", status="editor_approved")
            repo.create_artifact(book_id, 2, "draft", "drafted", "draft")
            result = repo.delete_chapter(book_id, 2)
            self.assertFalse(result["exported"])
            self.assertIsNone(repo.get_chapter_body(book_id, 2))
            self.assertIsNone(repo.latest_artifact(book_id, 2, "draft"))
            batch_id = repo.create_chapter_batch(book_id, 1)
            plans = repo.list_chapter_plan_rows(book_id, batch_id)
            self.assertEqual([2], [row["chapter_no"] for row in plans])

    def test_delete_exported_chapter_does_not_remove_continuity_history(self):
        with IsolatedEnv():
            repo = self.repo()
            book_id = repo.create_book("export-history", "test")
            repo.create_chapter_batch(book_id, 1)
            repo.save_chapter_body(book_id, 1, "chapter 1", "body", status="exported", export_id=7)
            memory = repo.create_memory(book_id, "chapter_memory", "chapter:1", {"summary": "kept"}, 1, 1, 7)
            result = repo.delete_chapter(book_id, 1)
            self.assertTrue(result["exported"])
            self.assertIsNone(repo.get_chapter_body(book_id, 1))
            self.assertEqual(memory["id"], repo.latest_memory(book_id, "chapter_memory", "chapter:1")["id"])

    def test_json_safe_converts_datetime_recursively(self):
        now = datetime(2026, 6, 9, 1, 2, 3, tzinfo=timezone.utc)
        payload = json_safe({"created_at": now, "items": [{"updated_at": now}]})
        self.assertEqual("2026-06-09T01:02:03+00:00", payload["created_at"])
        self.assertEqual("2026-06-09T01:02:03+00:00", payload["items"][0]["updated_at"])

    def test_import_profiles_accepts_markdown_json_fence(self):
        with IsolatedEnv():
            repo = self.repo()
            ids = repo.import_profiles(
                "authors",
                """```json id="author_skill_new_writer"
{
  "name": "测试代码块作者",
  "genre": "都市幻想",
  "pov_preference": "third_limited",
  "sentence_rhythm": "长短句自然混合",
  "dialogue_style": "潜台词",
  "payoff_preference": "克制兑现",
  "forbidden_items": "说明书式设定",
  "prompt_rules": "只输出正文"
}
```""",
            )
            profile = repo.get_profile("authors", ids[0])
            self.assertEqual("测试代码块作者", profile["name"])


if __name__ == "__main__":
    unittest.main()
