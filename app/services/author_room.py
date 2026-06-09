from __future__ import annotations

import json

from app.storage.repository import POV_LABELS, Repository, json_safe


class AuthorRoom:
    def __init__(self, repo: Repository):
        self.repo = repo

    def build_brief(self, book_id: int, chapter_no: int):
        ctx = self.repo.get_architecture_context(book_id, chapter_no)
        book = ctx["book"]
        plan = ctx["plan"]
        volume = ctx["volume"] or {}
        unit = ctx["arc"] or {}
        author = ctx.get("author_profile") or {}
        settings = ctx["settings"]
        pov = book.get("pov_policy") or settings.get("pov_policy") or "third_limited"
        brief = {
            "name": "本章写作任务",
            "chapter_no": chapter_no,
            "chapter_title": plan["title"],
            "target_chars": plan.get("target_chars") or settings.get("target_chars_max", 2600),
            "pov": POV_LABELS.get(pov, "第三人称有限视角"),
            "priority": "全书结构化大纲 > 当前卷纲 > 当前单元纲 > 本章细纲 > 连续性记忆",
            "author_style": {
                "name": author.get("name", "默认作者"),
                "sentence_rhythm": author.get("sentence_rhythm", ""),
                "dialogue_style": author.get("dialogue_style", ""),
                "payoff_preference": author.get("payoff_preference", ""),
                "forbidden_items": author.get("forbidden_items", ""),
                "prompt_rules": author.get("prompt_rules", ""),
            },
            "book_outline": {
                "estimated_total_words": book.get("estimated_total_words", 1000000),
                "outline": book.get("book_outline") or book.get("imported_outline") or book.get("story_mainline") or "",
                "worldbuilding_rule": "只作约束，不得说明书式写入正文。",
            },
            "volume_outline": {
                "title": volume.get("title", ""),
                "goal": volume.get("goal", ""),
                "core_conflict": volume.get("core_conflict", ""),
                "stage_payoff": volume.get("stage_payoff", ""),
                "character_progression": volume.get("character_progression", ""),
                "foreshadowing_plan": volume.get("foreshadowing_plan", ""),
            },
            "unit_outline": {
                "title": unit.get("title", ""),
                "goal": unit.get("goal", ""),
                "cause": unit.get("cause", ""),
                "process": unit.get("process", ""),
                "result": unit.get("result", ""),
                "payoff": unit.get("payoff", ""),
                "character_change": unit.get("character_change", ""),
                "foreshadowing_progress": unit.get("foreshadowing_progress", ""),
                "recommended_chapters": unit.get("recommended_chapters", 5),
            },
            "chapter_control": {
                "unique_task": plan.get("unique_task", ""),
                "core_event": plan.get("core_event", ""),
                "tech_progression": plan.get("tech_progression", ""),
                "character_roles": plan.get("character_roles", ""),
                "antagonist_move": plan.get("antagonist_move", ""),
                "external_pressure": plan.get("external_pressure", ""),
                "irreversible_change": plan.get("irreversible_change", ""),
                "ending_hook": plan.get("ending_hook", ""),
                "no_repeat_guard": plan.get("no_repeat_guard", ""),
                "objective": plan["objective"],
                "plot_summary": plan.get("plot_summary", ""),
                "allowed_reveals": plan["allowed_reveals"],
                "forbidden_reveals": plan["forbidden_reveals"],
                "pace_limit": plan["pace_limit"],
            },
            "story_shape": "严格执行本章细纲，从上一章结尾状态自然续写；第 1 章无上一章时，从开书设定和本章细纲进入正文。",
        }
        return self.repo.create_artifact(book_id, chapter_no, "author_brief", "ready", json.dumps(json_safe(brief), ensure_ascii=False, indent=2))
