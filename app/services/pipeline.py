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
        return self.generate_chapter(book_id, chapter_no)

    def generate_chapter(self, book_id: int, chapter_no: int, rewrite_feedback: str = "") -> dict[str, object]:
        run_id = self.repo.create_run(book_id, chapter_no)
        try:
            brief = self.author_room.build_brief(book_id, chapter_no)
            ref_pack = self.continuity.build_ref_pack(book_id, chapter_no, run_id)
            draft = self.writer.draft(book_id, chapter_no, brief.id, ref_pack.id, rewrite_feedback)
            review = self.editorial.review(book_id, chapter_no, draft.id)
            result = self._finalize_review(book_id, chapter_no, review)
            self.repo.finish_run(run_id, book_id, chapter_no, str(result["status"]))
            return {"run_id": run_id, "brief": brief, "ref_pack": ref_pack, "draft": draft, "review": review, **result}
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            failure = self.repo.create_artifact(book_id, chapter_no, "generation_error", "failed", message)
            self.repo.finish_run(run_id, book_id, chapter_no, "failed")
            return {"run_id": run_id, "status": "failed", "error": message, "failure": failure}

    def _finalize_review(self, book_id: int, chapter_no: int, review) -> dict[str, object]:
        data = json.loads(review.content)
        status = data["status"]
        if status == "approved":
            approved = self.repo.latest_artifact(book_id, chapter_no, "draft")
            if approved is None or approved.status != "editor_approved":
                raise ValueError("editor approved draft missing")
            plan = self.repo.get_chapter_plan(book_id, chapter_no)
            title = plan.title if plan else f"第{chapter_no}章"
            self.repo.save_chapter_body(book_id, chapter_no, title, approved.content, status="editor_approved")
            self.repo.resolve_generation_errors(book_id, chapter_no)
        return {"status": status, "review_data": data}

    def rewrite_and_review(self, book_id: int, chapter_no: int) -> dict[str, object]:
        task = self.repo.get_rewrite_task(book_id, chapter_no)
        if not task:
            return self.generate_chapter(book_id, chapter_no)
        attempts = int(task["attempts"] or 0)
        max_attempts = int(task["max_attempts"] or 3)
        if attempts >= max_attempts:
            self.repo.update_rewrite_task(int(task["id"]), "manual_required", attempts, "已达到三轮自动重写上限，请人工处理。")
            return {"status": "manual_required", "task": task}
        review = self.repo.get_artifact(int(task["review_artifact_id"]))
        feedback = review.content if review else "修复上一轮编辑意见。"
        self.repo.update_rewrite_task(int(task["id"]), "running", attempts + 1)
        result = self.generate_chapter(book_id, chapter_no, feedback)
        if result.get("status") == "approved":
            self.repo.update_rewrite_task(int(task["id"]), "fixed", attempts + 1)
        elif attempts + 1 >= max_attempts:
            self.repo.update_rewrite_task(int(task["id"]), "manual_required", attempts + 1, "已达到三轮自动重写上限，请人工处理。")
        else:
            self.repo.update_rewrite_task(int(task["id"]), "pending", attempts + 1)
        return result

    def generate_batch(self, book_id: int, batch_id: int) -> list[dict[str, object]]:
        batch = self.repo.get_chapter_batch(batch_id)
        if not batch:
            raise ValueError("章节批次不存在。")
        self.repo.update_batch_status(batch_id, "running", "开始生成正文。")
        results = []
        for plan in self.repo.list_chapter_plan_rows(book_id, batch_id):
            self.repo.update_batch_status(batch_id, "running", f"正在生成第 {plan['chapter_no']} 章：{plan['title']}")
            result = self.generate_chapter(book_id, int(plan["chapter_no"]))
            if result.get("status") == "rejected":
                for _ in range(3):
                    result = self.rewrite_and_review(book_id, int(plan["chapter_no"]))
                    if result.get("status") == "approved":
                        break
            results.append(result)
        failed = [r for r in results if r.get("status") != "approved"]
        self.repo.update_batch_status(batch_id, "manual_required" if failed else "editor_approved", "部分章节需要人工处理。" if failed else "生成完成，等待人工确认正文。")
        return results

    def generate_next_three(self, book_id: int) -> list[dict[str, object]]:
        batch_id = self.repo.create_chapter_batch(book_id)
        return self.generate_batch(book_id, batch_id)

    def manual_approve(self, book_id: int, chapter_no: int) -> dict[str, object]:
        body = self.repo.get_chapter_body(book_id, chapter_no)
        if not body:
            draft = self.repo.latest_artifact(book_id, chapter_no, "draft")
            if draft is None:
                raise ValueError("没有可确认的正文。")
            plan = self.repo.get_chapter_plan(book_id, chapter_no)
            self.repo.save_chapter_body(book_id, chapter_no, plan.title if plan else f"第{chapter_no}章", draft.content, "human_confirmed")
        else:
            self.repo.confirm_chapter_body(book_id, chapter_no)
        return {"status": "human_confirmed"}
