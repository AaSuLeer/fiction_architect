from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.config import get_settings
from app.factory import build_runtime
from app.services.planning_agent import PlanningAgent
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

    def test_planning_context_is_bounded_to_current_volume_and_neighbors(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            long_text = "长期大纲约束。" * 4000
            book_id = repo.create_book("规划预算书", long_text, book_outline=long_text, worldbuilding=long_text, estimated_total_words=600000)
            volumes = repo.list_volumes(book_id)
            self.assertGreaterEqual(len(volumes), 3)
            current_volume = volumes[1]
            arcs = repo.list_arcs(book_id, current_volume["id"])
            batch_id = repo.create_chapter_batch(book_id, 2, volume_id=current_volume["id"], arc_id=arcs[0]["id"])
            plans = repo.list_chapter_plan_rows(book_id, batch_id)
            ctx = repo.get_architecture_context(book_id, int(plans[0]["chapter_no"]))
            previous_volume, next_volume = pipe.planner._neighbor_volumes(book_id, ctx["volume"])
            compact = pipe.planner._compact_context(
                {
                    "book": ctx["book"],
                    "volume": ctx["volume"],
                    "previous_volume": previous_volume,
                    "next_volume": next_volume,
                    "unit": ctx["arc"],
                    "characters": ctx["characters"],
                    "canon": [{"content": "硬事实。" * 2000, "fact_type": "rule"} for _ in range(30)],
                    "batch": repo.get_chapter_batch(batch_id),
                    "chapters": [{"chapter_no": row["chapter_no"], "title": row["title"]} for row in plans],
                    "previous": {"body_excerpt": "上一章正文。" * 3000, "terminal_state": "上一章结尾。" * 1000},
                }
            )
            payload = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
            self.assertLessEqual(len(payload), 18000)
            self.assertEqual(current_volume["id"], compact["volume"]["id"])
            self.assertEqual(volumes[0]["id"], compact["volume_boundaries"]["previous"]["id"])
            self.assertEqual(volumes[2]["id"], compact["volume_boundaries"]["next"]["id"])

    def test_non_manual_titles_are_not_sent_as_planning_hints(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_book("旧标题不进提示", "主角线性推进")
            batch_id = repo.create_chapter_batch(book_id, 1)
            with repo.db.session() as conn:
                repo._execute(conn, "UPDATE chapter_plans SET title = ?, manual_edited = 0 WHERE book_id = ? AND chapter_no = ?", ("开局压迫", book_id, 1))
            plans = repo.list_chapter_plan_rows(book_id, batch_id)
            chapters = [{"chapter_no": row["chapter_no"], "title": row["title"] if int(row.get("manual_edited") or 0) == 1 else ""} for row in plans]
            self.assertEqual("", chapters[0]["title"])

    def test_planning_ignores_markdown_headings_as_character_names(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            context = {
                "book": {"title": "人物清洗测试"},
                "volume": {"goal": "当前卷目标"},
                "unit": {"goal": "当前单元目标", "process": "按单元推进"},
                "characters": [{"name": "# 主要人物小传"}, {"name": "顾临川"}],
                "canon": [],
                "batch": {"id": 1},
                "chapters": [{"chapter_no": 1, "title": ""}],
                "previous": {},
            }
            planned = pipe.planner._mock_plan(context)
            self.assertNotIn("# 主要人物小传", planned[0]["core_event"])
            self.assertIn("顾临川", planned[0]["core_event"])

    def test_planning_normalizer_accepts_loose_numeric_fields(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            item = pipe.planner._normalize_plan(
                {
                    "chapter_no": ["12"],
                    "title": "第12章",
                    "core_event": "主角处理当前单元的具体事件。",
                    "target_chars": ["2600字"],
                }
            )
            self.assertEqual(12, item["chapter_no"])
            self.assertEqual(2600, item["target_chars"])

    def test_planning_agent_fills_missing_model_chapters(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            context = {
                "book": {"title": "补齐测试"},
                "volume": {"goal": "当前卷目标"},
                "unit": {"goal": "当前单元目标", "process": "按单元推进"},
                "characters": [],
                "canon": [],
                "batch": {"id": 1},
                "chapters": [{"chapter_no": 1, "title": "一"}, {"chapter_no": 2, "title": "二"}, {"chapter_no": 3, "title": "三"}],
                "previous": {},
            }
            planned = pipe.planner._ensure_all_chapters_planned(context, [{"chapter_no": 1, "title": "一", "core_event": "已规划"}])
            self.assertEqual([1, 2, 3], [row["chapter_no"] for row in planned])
            self.assertTrue(planned[1]["core_event"])

    def test_planning_agent_falls_back_when_model_fails(self):
        class FailingLlm:
            settings = SimpleNamespace(llm_mode="compatible", llm_default_model="qwen-plus", llm_outline_model="qwen-max")

            def complete(self, *args, **kwargs):
                raise RuntimeError("timeout")

        with IsolatedEnv():
            repo = self.repo()
            book_id = repo.create_book("模型失败兜底书", "主角线性推进")
            batch_id = repo.create_chapter_batch(book_id, 3)
            agent = PlanningAgent(repo, FailingLlm())
            planned = agent.plan_chapter_batch(book_id, batch_id)
            rows = repo.list_chapter_plan_rows(book_id, batch_id)
            self.assertEqual(3, len(planned))
            self.assertEqual(3, len([row for row in rows if row["core_event"]]))
            self.assertEqual("planning", repo.get_chapter_batch(batch_id)["status"])

    def test_generated_template_title_is_not_preserved_on_replan(self):
        with IsolatedEnv():
            repo, pipe = build_runtime()
            book_id = repo.create_book("旧标题清理书", "主角线性推进")
            batch_id = repo.create_chapter_batch(book_id, 1)
            with repo.db.session() as conn:
                repo._execute(conn, "UPDATE chapter_plans SET title = ?, manual_edited = 0 WHERE book_id = ? AND chapter_no = ?", ("开局压迫", book_id, 1))
            repo.apply_planned_chapter_cards(
                book_id,
                batch_id,
                [
                    {
                        "chapter_no": 1,
                        "title": "第1章 新规划标题",
                        "objective": "新目标",
                        "core_event": "新事件",
                    }
                ],
            )
            plan = repo.get_chapter_plan_row(book_id, 1)
            self.assertEqual("第1章 新规划标题", plan["title"])

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
