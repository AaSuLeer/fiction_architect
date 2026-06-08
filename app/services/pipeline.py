from __future__ import annotations

import json

from app.llm import LlmClient, TextGuard
from app.services.author_room import AuthorRoom
from app.services.continuity_studio import ContinuityStudio
from app.services.editorial_department import EditorialDepartment
from app.services.writing_department import WritingDepartment
from app.storage.repository import Repository


class Pipeline:
    def __init__(self, repo: Repository, llm: LlmClient):
        self.repo = repo
        self.author_room = AuthorRoom(repo)
        self.continuity = ContinuityStudio(repo)
        self.writer = WritingDepartment(repo, llm)
        self.editorial = EditorialDepartment(repo, TextGuard())

    def run_chapter(self, book_id: int, chapter_no: int) -> dict[str, object]:
        run_id = self.repo.create_run(book_id, chapter_no)
        try:
            brief = self.author_room.build_brief(book_id, chapter_no)
            ref_pack = self.continuity.build_ref_pack(book_id, chapter_no)
            draft = self.writer.draft(book_id, chapter_no, brief.id, ref_pack.id)
            review = self.editorial.review(book_id, chapter_no, draft.id)
            review_data = json.loads(review.content)
            patch = None
            final_status = review_data["status"]
            if final_status == "approved":
                approved = self.repo.latest_artifact(book_id, chapter_no, "draft")
                if approved is None or approved.status != "approved":
                    raise ValueError("approved draft missing after review")
                patch = self.continuity.writeback(book_id, chapter_no, approved.id)
                plan = self.repo.get_chapter_plan(book_id, chapter_no)
                title = plan.title if plan else f"第{chapter_no}章"
                self.repo.save_chapter_body(book_id, chapter_no, title, approved.content)
            self.repo.finish_run(run_id, book_id, chapter_no, final_status)
            return {"run_id": run_id, "status": final_status, "brief": brief, "ref_pack": ref_pack, "draft": draft, "review": review, "patch": patch}
        except Exception:
            self.repo.finish_run(run_id, book_id, chapter_no, "failed")
            raise
