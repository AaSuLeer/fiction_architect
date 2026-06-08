from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.config import get_settings
from app.factory import build_runtime
from app.llm import TextGuard
from app.storage import Database, Repository, initialize_database


class IsolatedEnv:
    def __init__(self):
        self.original = os.environ.copy()
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "fiction_architect_test.db"

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


class ArchitectureTests(unittest.TestCase):
    def runtime(self):
        settings = get_settings()
        db = Database(settings)
        initialize_database(db)
        repo = Repository(db)
        return repo

    def test_sqlite_demo_initializes_four_layer_architecture(self):
        with IsolatedEnv():
            repo = self.runtime()
            book_id = repo.create_demo_book()
            plans = repo.list_chapter_plans(book_id)
            self.assertEqual(3, len(plans))
            self.assertEqual([1, 2, 3], [plan.chapter_no for plan in plans])
            ctx = repo.get_architecture_context(book_id, 1)
            self.assertEqual("第一卷：废校开门", ctx["volume"]["title"])
            self.assertEqual("入学验词", ctx["arc"]["title"])
            self.assertIn("不能解释完整世界观", plans[2].forbidden_reveals)

    def test_pipeline_approves_clean_mock_and_writes_body(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_demo_book()
            result = pipe.run_chapter(book_id, 1)
            self.assertEqual("approved", result["status"])
            body = repo.get_chapter_body(book_id, 1)
            self.assertIsNotNone(body)
            patch = repo.latest_artifact(book_id, 1, "continuity_patch")
            self.assertIsNotNone(patch)
            self.assertEqual("candidate", patch.status)

    def test_contaminated_body_is_rejected(self):
        guard = TextGuard()
        result = guard.check_body("本章交付会比上一章更稳，根据规则由连续性工作室推进。")
        self.assertFalse(result.passed)
        self.assertGreaterEqual(len(result.problems), 3)

    def test_unapproved_draft_cannot_writeback(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_demo_book()
            draft = repo.create_artifact(book_id, 1, "draft", "drafted", "普通草稿。普通草稿。普通草稿。普通草稿。普通草稿。普通草稿。")
            with self.assertRaises(ValueError):
                pipe.continuity.writeback(book_id, 1, draft.id)

    def test_editor_rejects_short_draft(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_demo_book()
            draft = repo.create_artifact(book_id, 1, "draft", "drafted", "林砚站在台前。倒计时只剩三十息。他伸手改了一个字，赢下资格，也欠下代价。")
            review = pipe.editorial.review(book_id, 1, draft.id)
            self.assertEqual("rejected", review.status)
            self.assertIn("字数不达标", review.content)

    def test_first_person_policy_is_configurable(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_demo_book()
            controls = repo.get_book_controls(book_id)
            repo.update_style_and_settings(
                book_id,
                controls["style"]["rules"],
                controls["settings"]["market_channel"],
                50,
                5000,
                controls["settings"]["chapter_unit_size"],
                "first_person",
                controls["settings"]["hook_policy"],
                controls["settings"]["pacing_policy"],
            )
            sample = "我站在验词台前，倒计时只剩三十息。\n\n我伸手按住名册，先试探红印，再反问考官。\n\n最后我赢下临时资格，也欠下三日后的代价。"
            draft = repo.create_artifact(book_id, 1, "draft", "drafted", sample)
            review = pipe.editorial.review(book_id, 1, draft.id)
            self.assertNotIn("人称错误", review.content)

    def test_story_arc_limits_chapters_one_to_three(self):
        with IsolatedEnv():
            repo = self.runtime()
            book_id = repo.create_demo_book()
            contexts = [repo.get_architecture_context(book_id, chapter_no) for chapter_no in [1, 2, 3]]
            self.assertEqual(1, len({ctx["arc"]["id"] for ctx in contexts}))
            self.assertTrue(all("不能" in ctx["plan"]["pace_limit"] or "只" in ctx["plan"]["pace_limit"] for ctx in contexts))


if __name__ == "__main__":
    unittest.main()
