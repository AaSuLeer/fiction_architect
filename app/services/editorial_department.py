from __future__ import annotations

import json

from app.llm import TextGuard
from app.storage.repository import Repository


class EditorialDepartment:
    def __init__(self, repo: Repository, guard: TextGuard):
        self.repo = repo
        self.guard = guard

    def review(self, book_id: int, chapter_no: int, draft_id: int):
        draft = self.repo.get_artifact(draft_id)
        if draft is None:
            raise ValueError("editorial blocked: missing draft")
        result = self.guard.check_body(draft.content)
        ctx = self.repo.get_architecture_context(book_id, chapter_no)
        plan = ctx["plan"]
        problems = list(result.problems)
        if plan["forbidden_reveals"] and any(key in draft.content for key in ["废校真正来历", "完整世界观", "卷级终局"]):
            problems.append("推进过快：触碰了本章 forbidden_reveals。")
        status = "approved" if not problems else "rejected"
        report = {
            "department": "editorial_department",
            "draft_id": draft_id,
            "status": status,
            "problems": problems,
            "checks": [
                "正文污染",
                "说明书式写作",
                "节奏推进",
                "AI模板化风险",
                "连续性风险",
            ],
        }
        review = self.repo.create_artifact(book_id, chapter_no, "review", status, json.dumps(report, ensure_ascii=False, indent=2))
        if status == "approved":
            self.repo.create_artifact(book_id, chapter_no, "draft", "approved", draft.content, visibility="approved")
        return review

