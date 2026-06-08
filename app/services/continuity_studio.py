from __future__ import annotations

import json

from app.storage.repository import Repository


class ContinuityStudio:
    def __init__(self, repo: Repository):
        self.repo = repo

    def build_ref_pack(self, book_id: int, chapter_no: int):
        ctx = self.repo.get_architecture_context(book_id, chapter_no)
        ref_pack = {
            "department": "continuity_studio",
            "book_outline": "全书层：主角从废校底层规则里逐步拿回解释权。当前章只能触碰局部规则。",
            "volume_outline": ctx["volume"],
            "unit_outline": ctx["arc"],
            "chapter_detail": ctx["plan"],
            "characters": ctx["characters"],
            "foreshadowings": ctx["foreshadowings"],
            "canon": ctx["canon"],
            "visibility_rules": ctx["visibility"],
            "writing_gate": [
                "只允许展示当前角色知道的信息。",
                "世界规则通过处罚、奖励、交易和失败露出。",
                "人物关系通过选择和反应推进，不通过说明段落推进。",
                "不得越过 pace_limit。",
            ],
        }
        return self.repo.create_artifact(book_id, chapter_no, "ref_pack", "ready", json.dumps(ref_pack, ensure_ascii=False, indent=2))

    def writeback(self, book_id: int, chapter_no: int, approved_draft_id: int):
        draft = self.repo.get_artifact(approved_draft_id)
        if draft is None or draft.status != "approved":
            raise ValueError("continuity writeback blocked: draft is not approved")
        patch = {
            "department": "continuity_studio",
            "source_draft_id": approved_draft_id,
            "status": "candidate",
            "updates": [
                "本章确认主角可通过词条细节规避一次规则处罚。",
                "第一条校规继续保持未完全揭露。",
                "主角获得临时优势，但仍欠下规则代价。",
            ],
        }
        return self.repo.create_artifact(book_id, chapter_no, "continuity_patch", "candidate", json.dumps(patch, ensure_ascii=False, indent=2))

