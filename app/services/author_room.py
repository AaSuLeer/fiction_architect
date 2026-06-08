from __future__ import annotations

import json

from app.storage.repository import POV_LABELS, Repository


class AuthorRoom:
    def __init__(self, repo: Repository):
        self.repo = repo

    def build_brief(self, book_id: int, chapter_no: int):
        ctx = self.repo.get_architecture_context(book_id, chapter_no)
        book = ctx["book"]
        plan = ctx["plan"]
        author = ctx.get("author_profile") or {}
        settings = ctx["settings"]
        pov = book.get("pov_policy") or settings.get("pov_policy") or "third_limited"
        brief = {
            "name": "本章写作任务",
            "chapter_no": chapter_no,
            "chapter_title": plan["title"],
            "target_chars": plan.get("target_chars") or settings.get("target_chars_max", 2600),
            "pov": POV_LABELS.get(pov, "第三人称有限视角"),
            "author_style": {
                "name": author.get("name", "默认作者"),
                "sentence_rhythm": author.get("sentence_rhythm", ""),
                "dialogue_style": author.get("dialogue_style", ""),
                "payoff_preference": author.get("payoff_preference", ""),
                "forbidden_items": author.get("forbidden_items", ""),
                "prompt_rules": author.get("prompt_rules", ""),
            },
            "book_setup": {
                "genre": book.get("genre", ""),
                "market_channel": book.get("market_channel", ""),
                "target_reader": book.get("target_reader", ""),
                "story_mainline": book.get("story_mainline", ""),
                "worldbuilding": "仅作写作约束，不得说明书式写入正文。",
            },
            "chapter_control": {
                "objective": plan["objective"],
                "plot_summary": plan.get("plot_summary", ""),
                "allowed_reveals": plan["allowed_reveals"],
                "forbidden_reveals": plan["forbidden_reveals"],
                "pace_limit": plan["pace_limit"],
            },
            "story_shape": "必须有起因、经过、结果；爽点来自行动和局势变化；结尾留下代价或新钩子。",
        }
        return self.repo.create_artifact(book_id, chapter_no, "author_brief", "ready", json.dumps(brief, ensure_ascii=False, indent=2))
