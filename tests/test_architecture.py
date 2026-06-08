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
        self.db_path = Path(self.tmp.name) / "architecture.db"

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
    def repo(self) -> Repository:
        settings = get_settings()
        db = Database(settings)
        initialize_database(db)
        return Repository(db)

    def test_formal_book_initializes_four_layer_architecture(self):
        with IsolatedEnv():
            repo = self.repo()
            book_id = repo.create_book("架构测试书", "主角在规则压迫下反击", story_mainline="三章完成一次小闭环")
            plans = repo.list_chapter_plans(book_id)
            self.assertEqual([1, 2, 3], [plan.chapter_no for plan in plans])
            ctx = repo.get_architecture_context(book_id, 1)
            self.assertIn("第一卷", ctx["volume"]["title"])
            self.assertIn("前三章", ctx["arc"]["title"])
            self.assertEqual(ctx["arc"]["id"], repo.get_architecture_context(book_id, 3)["arc"]["id"])

    def test_pipeline_editor_approval_does_not_write_continuity_before_export(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_book("生成测试书", "主角夺回解释权", target_chars_min=900, target_chars_max=1800)
            result = pipe.generate_chapter(book_id, 1)
            self.assertEqual("approved", result["status"])
            body = repo.get_chapter_body(book_id, 1)
            self.assertEqual("editor_approved", body["status"])
            self.assertIsNone(repo.latest_memory(book_id, "chapter_memory", "chapter:1"))

    def test_exported_body_writes_memory_and_atom_candidates(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_book("导出记忆书", "主角用证据反击", target_chars_min=50, target_chars_max=5000)
            text = "起因是公开压迫。经过是主角找到证据并反击。结果是对手退让，但留下新的代价。" * 20
            repo.save_chapter_body(book_id, 1, "第一章：反击", text, "human_confirmed")
            record = repo.create_export_record(book_id, "docx", "dummy.docx")
            repo.mark_exported(book_id, int(record["id"]))
            pipe.continuity.writeback_from_export(book_id, int(record["id"]))
            self.assertIsNotNone(repo.latest_memory(book_id, "chapter_memory", "chapter:1"))
            self.assertEqual(1, len(repo.list_atoms(book_id, status="candidate", chapter_no=1)))

    def test_contaminated_body_is_rejected(self):
        result = TextGuard().check_body("交付说明：根据规则，本章由连续性工作室处理，审稿通过后比上一章更稳。")
        self.assertFalse(result.passed)
        self.assertGreaterEqual(len(result.problems), 3)

    def test_first_person_policy_is_configurable(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_book("第一人称书", "我从失败里反击", pov_policy="first_person", target_chars_min=20, target_chars_max=5000)
            sample = "我站在验词台前，倒计时只剩三十息。起因是对手逼我退场。经过是我按住名册反问考官。结果是我赢下临时资格，也欠下三日后的代价。"
            draft = repo.create_artifact(book_id, 1, "draft", "drafted", sample)
            review = pipe.editorial.review(book_id, 1, draft.id)
            self.assertNotIn("人称错误", review.content)


if __name__ == "__main__":
    unittest.main()
