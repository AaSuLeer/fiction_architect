from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.config import get_settings
from app.factory import build_runtime
from app.storage import Database, Repository, initialize_database


class IsolatedEnv:
    def __init__(self):
        self.original = os.environ.copy()
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "workbench.db"

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


class WorkbenchRebuildTests(unittest.TestCase):
    def repo(self) -> Repository:
        settings = get_settings()
        db = Database(settings)
        initialize_database(db)
        return Repository(db)

    def test_duplicate_active_book_is_blocked_and_archive_hides_it(self):
        with IsolatedEnv():
            repo = self.repo()
            book_id = repo.create_book("同名书", "正式作品")
            with self.assertRaises(ValueError):
                repo.create_book("同名书", "另一本正式作品")
            repo.archive_book(book_id)
            self.assertEqual([], repo.list_books("active"))
            self.assertEqual(["同名书"], [book.title for book in repo.list_books("archived")])
            repo.restore_book(book_id)
            self.assertEqual(["同名书"], [book.title for book in repo.list_books("active")])

    def test_demo_and_sample_are_removed_from_business_flow(self):
        with IsolatedEnv():
            repo = self.repo()
            with self.assertRaises(ValueError):
                repo.create_demo_book()
            self.assertEqual([], repo.list_books("sample"))

    def test_new_book_keeps_opening_fields_and_chinese_pov_label(self):
        with IsolatedEnv():
            repo = self.repo()
            book_id = repo.create_book(
                "开书字段",
                "核心卖点",
                genre="都市异能",
                market_channel="番茄/男频",
                target_reader="强钩子读者",
                pov_policy="first_person",
                story_mainline="长期夺回解释权",
                worldbuilding="词条有代价",
                imported_outline="第一卷起势",
                characters_text="林彻：主角小传",
            )
            record = repo.get_book_record(book_id)
            controls = repo.get_book_controls(book_id)
            self.assertEqual("都市异能", record["genre"])
            self.assertEqual("词条有代价", record["worldbuilding"])
            self.assertEqual("第一人称主角视角", controls["pov_label"])

    def test_book_author_editor_overrides_do_not_mutate_global_resources(self):
        with IsolatedEnv():
            repo = self.repo()
            book_id = repo.create_book("资源覆盖书", "测试资源")
            author_id = repo.save_profile(
                "authors",
                {
                    "name": "资源作者",
                    "genre": "都市",
                    "pov_preference": "first_person",
                    "sentence_rhythm": "口语化",
                    "dialogue_style": "直接",
                    "payoff_preference": "反击",
                    "forbidden_items": "说明书",
                    "prompt_rules": "用我叙述",
                },
            )
            editor_id = repo.save_profile(
                "editors",
                {
                    "name": "资源编辑",
                    "platform": "新平台",
                    "word_count_rule": "2000 字以上",
                    "pov_rule": "跟随作品",
                    "structure_rule": "起因经过结果",
                    "payoff_rule": "有爽点",
                    "pollution_rule": "无部门话术",
                    "reject_threshold": 1,
                },
            )
            repo.assign_resources(book_id, author_id, editor_id)
            repo.update_book_author_profile(book_id, {"name": "本书作者", "genre": "都市", "pov_preference": "first_person", "sentence_rhythm": "快", "dialogue_style": "短", "payoff_preference": "强", "forbidden_items": "无", "prompt_rules": "本书规则", "sample_summary": "笔记"})
            repo.update_book_editor_profile(book_id, {"name": "本书编辑", "platform": "本书平台", "word_count_rule": "900+", "pov_rule": "跟随", "structure_rule": "完整", "payoff_rule": "有效", "pollution_rule": "严格", "reject_threshold": 1})
            self.assertEqual("资源作者", repo.get_profile("authors", author_id)["name"])
            self.assertEqual("资源编辑", repo.get_profile("editors", editor_id)["name"])
            controls = repo.get_book_controls(book_id)
            self.assertEqual("本书作者", controls["author_profile"]["name"])
            self.assertEqual("本书编辑", controls["editor_profile"]["name"])

    def test_chapter_batch_numbers_continue_after_seed_plans(self):
        with IsolatedEnv():
            repo = self.repo()
            book_id = repo.create_book("批次书", "测试批次")
            batch_id = repo.create_chapter_batch(book_id, 3)
            batch = repo.get_chapter_batch(batch_id)
            plans = repo.list_chapter_plan_rows(book_id, batch_id)
            self.assertEqual((4, 6), (batch["start_chapter"], batch["end_chapter"]))
            self.assertEqual([4, 5, 6], [row["chapter_no"] for row in plans])

    def test_rejected_draft_creates_rewrite_task(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_book("拒稿书", "测试拒稿")
            draft = repo.create_artifact(book_id, 1, "draft", "drafted", "交付：根据规则，本章比上一章更稳。")
            review = pipe.editorial.review(book_id, 1, draft.id)
            self.assertEqual("rejected", review.status)
            self.assertIsNotNone(repo.get_rewrite_task(book_id, 1))

    def test_ref_pack_is_bounded_and_logs_retrieval(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_book("资料包书", "测试资料包")
            for no in range(1, 101):
                repo.create_memory(book_id, "chapter_memory", f"chapter:{no}", {"summary": f"第 {no} 章记忆"}, no, no)
            ref_pack = pipe.continuity.build_ref_pack(book_id, 3)
            self.assertLessEqual(ref_pack.content.count("chapter_memory"), 6)
            self.assertGreaterEqual(len(repo.list_retrieval_logs(book_id)), 1)

    def test_unapproved_atoms_are_not_used_in_ref_pack(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_book("事实池书", "测试事实")
            repo.create_atom(book_id, 1, "secret", "未批准秘密", status="candidate", visible_after_chapter=1)
            ref_pack = pipe.continuity.build_ref_pack(book_id, 2)
            self.assertNotIn("未批准秘密", ref_pack.content)
            atom = repo.list_atoms(book_id)[0]
            repo.update_atom_status(int(atom["id"]), "approved")
            ref_pack = pipe.continuity.build_ref_pack(book_id, 2)
            self.assertIn("未批准秘密", ref_pack.content)


if __name__ == "__main__":
    unittest.main()
