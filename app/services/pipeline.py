from __future__ import annotations

from app.llm import LlmClient
from app.storage.repository import Repository
from app.workflow import WorkflowKernel


class Pipeline:
    """Compatibility facade around the rebuilt workflow kernel.

    Old routes and a few tests still call Pipeline, but the production truth now
    lives in WorkflowKernel plus database state tables.
    """

    def __init__(self, repo: Repository, llm: LlmClient):
        self.repo = repo
        self.workflow = WorkflowKernel(repo, llm)
        self.continuity = self.workflow.continuity
        self.planner = self.workflow.planner
        self.writer = self.workflow.writer
        self.editorial = self.workflow.editor

    def run_chapter(self, book_id: int, chapter_no: int) -> dict[str, object]:
        return self.generate_chapter(book_id, chapter_no)

    def generate_chapter(self, book_id: int, chapter_no: int, rewrite_feedback: str = "") -> dict[str, object]:
        self._ensure_planned_for_compat(book_id, chapter_no)
        return self.workflow.draft_next_chapter_flow(book_id, chapter_no, rewrite_feedback)

    def plan_batch(self, book_id: int, batch_id: int) -> list[dict[str, object]]:
        batch = self.repo.get_chapter_batch(batch_id)
        if not batch:
            raise ValueError("chapter_batch_missing")
        run = self.repo.create_workflow_run(book_id, "plan_next_chapter_flow", payload={"batch_id": batch_id})
        self.repo.create_workflow_event(int(run["id"]), book_id, None, "candidate_window_reused", "复用旧批次作为候选窗口。", {"batch_id": batch_id})
        planned = self.planner.plan_chapter_batch(book_id, batch_id)
        candidates = []
        for item in planned:
            errors = self.workflow.validate_chapter_work_order(item)
            candidate = self.repo.upsert_chapter_candidate(
                book_id,
                int(item["chapter_no"]),
                self.workflow._work_order_from_plan(item),
                volume_id=item.get("volume_id") or batch.get("volume_id"),
                arc_id=item.get("arc_id") or batch.get("arc_id"),
                status="invalid" if errors else "candidate",
                validation_errors=errors,
            )
            candidates.append(candidate)
        self.repo.update_workflow_run(int(run["id"]), "completed", "candidates_ready", 100, payload={"batch_id": batch_id, "candidate_count": len(candidates)})
        self.repo.update_batch_status(batch_id, "candidate_ready", "候选章节已生成，正式写作将按单章状态机推进。", "")
        return [dict(row) for row in candidates]

    def generate_batch(self, book_id: int, batch_id: int) -> list[dict[str, object]]:
        batch = self.repo.get_chapter_batch(batch_id)
        if not batch:
            raise ValueError("chapter_batch_missing")
        self.repo.update_batch_status(batch_id, "running", "正在推进当前 active chapter。后续章节等待发布门禁。", "")
        candidates = self.repo.list_chapter_candidates(book_id, status="candidate", limit=1)
        chapter_no = int(candidates[0]["chapter_no"]) if candidates else int(batch["start_chapter"])
        result = self.workflow.draft_next_chapter_flow(book_id, chapter_no)
        if result.get("status") == "approved":
            self.repo.update_batch_status(
                batch_id,
                "waiting_previous_fix",
                f"第 {chapter_no} 章已通过编辑，等待人工确认、导出并发布后再推进下一章。",
                f"stopped_on_chapter={chapter_no}; waiting_for_publish",
            )
        else:
            self.repo.update_batch_status(
                batch_id,
                "waiting_fix",
                f"第 {chapter_no} 章需要返工，后续章节不会进入写作。",
                str(result.get("error") or result.get("failure_code") or result.get("status")),
            )
        return [result]

    def generate_next_three(self, book_id: int) -> list[dict[str, object]]:
        planned = self.workflow.plan_next_chapter_flow(book_id, 3)
        candidates = planned.get("candidates") or []
        if not candidates:
            return []
        return [self.workflow.draft_next_chapter_flow(book_id, int(candidates[0]["chapter_no"]))]

    def rewrite_and_review(self, book_id: int, chapter_no: int) -> dict[str, object]:
        return self.workflow.rework_flow(book_id, chapter_no)

    def manual_approve(self, book_id: int, chapter_no: int) -> dict[str, object]:
        body = self.repo.get_chapter_body(book_id, chapter_no)
        if not body:
            draft = self.repo.latest_chapter_draft(book_id, chapter_no)
            if draft is None:
                raise ValueError("no draft to approve")
            plan = self.repo.get_chapter_plan(book_id, chapter_no)
            self.repo.save_chapter_body(
                book_id,
                chapter_no,
                plan.title if plan else f"第{chapter_no}章",
                str(draft.get("content") or ""),
                "human_confirmed",
            )
        else:
            self.repo.confirm_chapter_body(book_id, chapter_no)
        self.repo.set_chapter_task_status(book_id, chapter_no, "human_release_check")
        return {"status": "human_confirmed"}

    def _ensure_planned_for_compat(self, book_id: int, chapter_no: int) -> None:
        plan = self.repo.get_chapter_plan_row(book_id, chapter_no)
        candidate = self.repo.get_chapter_candidate(book_id, chapter_no)
        task = self.repo.get_chapter_task(book_id, chapter_no)
        if candidate or (task and task.get("mission")):
            return
        batch_id = int(plan["batch_id"]) if plan and plan.get("batch_id") else 0
        if not batch_id:
            batches = self.repo.list_chapter_batches(book_id)
            for batch in batches:
                if int(batch["start_chapter"]) <= chapter_no <= int(batch["end_chapter"]):
                    batch_id = int(batch["id"])
                    break
        if batch_id:
            self.plan_batch(book_id, batch_id)
