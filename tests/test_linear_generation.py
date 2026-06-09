from __future__ import annotations

import json
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
        self.db_path = Path(self.tmp.name) / "linear.db"

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


class LinearGenerationTests(unittest.TestCase):
    def repo(self) -> Repository:
        settings = get_settings()
        db = Database(settings)
        initialize_database(db)
        return Repository(db)

    def test_chapter_cards_have_concrete_structure_fields(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_book("结构细纲书", "主角线性推进")
            batch_id = repo.create_chapter_batch(book_id, 5)
            pipe.plan_batch(book_id, batch_id)
            plans = repo.list_chapter_plan_rows(book_id, batch_id)
            self.assertEqual(5, len(plans))
            core_events = {row["core_event"] for row in plans}
            self.assertEqual(5, len(core_events))
            for row in plans:
                self.assertTrue(row["unique_task"])
                self.assertTrue(row["core_event"])
                self.assertTrue(row["tech_progression"])
                self.assertTrue(row["irreversible_change"])
                self.assertNotIn("承接单元起因，推进经过，并为结果兑现蓄力", row["objective"])

    def test_reused_legacy_card_gets_structure_without_overwriting_manual_text(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_book("旧卡片复用书", "主角线性推进")
            repo.create_chapter_batch(book_id, 1)
            repo.update_chapter_plan(
                book_id,
                1,
                "第1章 手写标题",
                "服务《旧单元》第1/3步：承接单元起因，推进经过，并为结果兑现蓄力。",
                "",
                "",
                "",
                "本章留下下一步钩子。",
                2600,
            )
            batch_id = repo.create_chapter_batch(book_id, 1)
            pipe.plan_batch(book_id, batch_id)
            plan = repo.list_chapter_plan_rows(book_id, batch_id)[0]
            self.assertEqual("第1章 手写标题", plan["title"])
            self.assertTrue(plan["unique_task"])
            self.assertTrue(plan["core_event"])
            self.assertNotIn("承接单元起因，推进经过，并为结果兑现蓄力", plan["objective"])

    def test_ref_pack_contains_previous_chapter_body(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_book("上一章正文书", "主角线性推进")
            batch_id = repo.create_chapter_batch(book_id, 2)
            pipe.plan_batch(book_id, batch_id)
            previous = "上一章结尾：主角已经拿到临时验证权限，团队在旧实验室集合，门外传来新的封锁通知。"
            repo.save_chapter_body(book_id, 1, "第一章", previous, status="editor_approved")
            ref = pipe.continuity.build_ref_pack(book_id, 2)
            content = json.loads(ref.content)
            self.assertIn("临时验证权限", content["previous_chapter_body"])
            self.assertIn("上一章状态", content["previous_chapter_terminal_state"])
            self.assertGreaterEqual(len(content["completed_function_history"]), 1)

    def test_batch_stops_when_previous_chapter_is_not_fixed(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_book("线性停机书", "主角线性推进", target_chars_min=5000, target_chars_max=5600)
            batch_id = repo.create_chapter_batch(book_id, 3)
            pipe.plan_batch(book_id, batch_id)
            results = pipe.generate_batch(book_id, batch_id)
            batch = repo.get_chapter_batch(batch_id)
            generated = [row["chapter_no"] for row in repo.list_chapter_bodies(book_id)]
            self.assertLess(len(results), 3)
            self.assertEqual("waiting_previous_fix", batch["status"])
            self.assertIn("stopped_on_chapter=1", batch["error"])
            self.assertNotIn(2, generated)

    def test_generation_auto_plans_pending_batch(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_book("空细纲阻断书", "主角线性推进", target_chars_min=20, target_chars_max=1800)
            repo.create_chapter_batch(book_id, 1)
            result = pipe.generate_chapter(book_id, 1)
            self.assertEqual("approved", result["status"])
            plan = repo.get_chapter_plan_row(book_id, 1)
            self.assertNotIn("待规划", plan["objective"])

    def test_editor_rejects_permission_regression(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_book("权限回退书", "主角线性推进", target_chars_min=20, target_chars_max=5000)
            batch_id = repo.create_chapter_batch(book_id, 2)
            pipe.plan_batch(book_id, batch_id)
            repo.save_chapter_body(book_id, 1, "第一章", "主角已经获得验证权限，小组成立，结论通过。", status="editor_approved")
            body = ("主角说：“我会处理。”随后他需要重新申请验证权限，再次争取小组资源。起因是封锁，经过是他走进会议室反击，结果是留下新的代价。") * 10
            draft = repo.create_artifact(book_id, 2, "draft", "drafted", body)
            review = pipe.editorial.review(book_id, 2, draft.id)
            self.assertEqual("rejected", review.status)
            self.assertIn("连续性回退", review.content)

    def test_editor_does_not_treat_dialogue_i_as_first_person_narration(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_book("对白人称书", "主角线性推进", pov_policy="third_limited", target_chars_min=20, target_chars_max=5000)
            batch_id = repo.create_chapter_batch(book_id, 1)
            pipe.plan_batch(book_id, batch_id)
            dialogue = "他说：“我知道我会输，但我必须试。我们不能退。”"
            body = ("起因是封锁压到门前。经过是林砚走到桌前按下证据并反问。结果是对手退让，留下新的代价。" + dialogue) * 10
            draft = repo.create_artifact(book_id, 1, "draft", "drafted", body)
            review = pipe.editorial.review(book_id, 1, draft.id)
            self.assertNotIn("人称错误", review.content)

    def test_editor_rejects_body_that_misses_chapter_outline(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_book("纲要贴合书", "主角线性推进", target_chars_min=20, target_chars_max=5000)
            batch_id = repo.create_chapter_batch(book_id, 1)
            pipe.plan_batch(book_id, batch_id)
            repo.update_chapter_plan(book_id, 1, "一", "目标", "", "", "", "梗概", 1000, core_event="主角在钟楼交出密信", tech_progression="密信改变交易条件", irreversible_change="同盟破裂")
            body = "小镇的雨下了一夜，陌生人在酒馆里听了一首旧歌，又买了一匹马离开。" * 10
            draft = repo.create_artifact(book_id, 1, "draft", "drafted", body)
            review = pipe.editorial.review(book_id, 1, draft.id)
            self.assertEqual("rejected", review.status)
            self.assertIn("纲要贴合不足", review.content)


if __name__ == "__main__":
    unittest.main()
