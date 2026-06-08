from __future__ import annotations

import json

from app.storage.repository import Repository


class AuthorRoom:
    def __init__(self, repo: Repository):
        self.repo = repo

    def build_brief(self, book_id: int, chapter_no: int):
        ctx = self.repo.get_architecture_context(book_id, chapter_no)
        plan = ctx["plan"]
        arc = ctx["arc"]
        volume = ctx["volume"]
        style = ctx["style"]
        brief = {
            "department": "author_room",
            "chapter_no": chapter_no,
            "chapter_title": plan["title"],
            "style_lock": style["rules"],
            "chapter_objective": plan["objective"],
            "unit_goal": arc["goal"],
            "volume_goal": volume["goal"],
            "pressure_rotation": arc["pressure"],
            "allowed_reveals": plan["allowed_reveals"],
            "forbidden_reveals": plan["forbidden_reveals"],
            "pace_limit": plan["pace_limit"],
            "market_shape": [
                "第一屏必须出现可计量压力、惩罚、排名或公开比较。",
                "爽点必须从行动中产生，不能靠旁白宣布主角很强。",
                "本章只解决章节目标，不提前解决单元、卷或全书问题。",
            ],
            "anti_template": [
                "句长自然变化，避免连续同构短句或整段长句。",
                "细节只服务动作、证据、代价、规则或回收。",
                "不得把大纲、世界观、人设关系写成说明书。",
            ],
        }
        return self.repo.create_artifact(book_id, chapter_no, "author_brief", "ready", json.dumps(brief, ensure_ascii=False, indent=2))

