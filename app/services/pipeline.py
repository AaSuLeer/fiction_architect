from __future__ import annotations

import json

from app.llm import LlmClient, TextGuard
from app.services.continuity_studio import ContinuityLedgerService
from app.services.editorial_department import EditorialDepartment
from app.services.planning_agent import PlanningAgent
from app.services.writing_department import WritingDepartment
from app.storage.repository import Repository


class Pipeline:
    def __init__(self, repo: Repository, llm: LlmClient):
        self.repo = repo
        self.continuity = ContinuityLedgerService(repo)
        self.planner = PlanningAgent(repo, llm)
        self.writer = WritingDepartment(repo, llm)
        self.editorial = EditorialDepartment(repo, TextGuard())

    def run_chapter(self, book_id: int, chapter_no: int) -> dict[str, object]:
        return self.generate_chapter(book_id, chapter_no)

    def generate_chapter(self, book_id: int, chapter_no: int, rewrite_feedback: str = "") -> dict[str, object]:
        run_id = self.repo.create_production_run(book_id, chapter_no)
        try:
            self._auto_plan_if_needed(book_id, chapter_no)
            self._ensure_chapter_plan_ready(book_id, chapter_no)
            self.repo.assert_can_enter_drafting(book_id, chapter_no)
            task = self.repo.ensure_chapter_task(book_id, chapter_no)
            self.repo.set_chapter_task_status(book_id, chapter_no, "drafting")
            packet = self.continuity.build_construction_packet(book_id, chapter_no, run_id)
            draft = self.writer.draft_from_packet(book_id, chapter_no, packet, rewrite_feedback)
            self.repo.set_chapter_task_status(book_id, chapter_no, "editorial_review")
            decision = self.editorial.review_draft(book_id, chapter_no, draft, run_id)
            result = self._finalize_decision(book_id, chapter_no, draft, decision)
            self.repo.finish_production_run(run_id, book_id, chapter_no, str(result["status"]), str(result.get("failure_code", "")))
            return {"run_id": run_id, "task": task, "construction_packet": packet, "draft": draft, "decision": decision, **result}
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self.repo.finish_production_run(run_id, book_id, chapter_no, "failed", "runtime_error", message)
            try:
                self.repo.set_chapter_task_status(book_id, chapter_no, "rewrite_needed")
            except Exception:
                pass
            return {"run_id": run_id, "status": "failed", "error": message, "failure_code": "runtime_error"}

    def _auto_plan_if_needed(self, book_id: int, chapter_no: int) -> None:
        plan = self.repo.get_chapter_plan_row(book_id, chapter_no)
        if not plan:
            return
        text = "\n".join(str(plan.get(field) or "") for field in ["objective", "plot_summary", "unique_task", "core_event"])
        if "待规划" in text and plan.get("batch_id"):
            self.plan_batch(book_id, int(plan["batch_id"]))

    def plan_batch(self, book_id: int, batch_id: int) -> list[dict[str, object]]:
        try:
            self.repo.update_batch_status(batch_id, "planning_running", "正在调用规划 Agent 生成章节细纲。", "")
            return self.planner.plan_chapter_batch(book_id, batch_id)
        except Exception as exc:
            self.repo.update_batch_status(batch_id, "planning_failed", "章节规划失败，请重试或手写细纲。", f"{type(exc).__name__}: {exc}")
            return []

    def _ensure_chapter_plan_ready(self, book_id: int, chapter_no: int) -> None:
        plan = self.repo.get_chapter_plan_row(book_id, chapter_no)
        if not plan:
            raise ValueError("chapter_plan_missing")
        blocked = [
            "待规划",
            "承接单元起因，推进经过，并为结果兑现蓄力",
            "本章留下下一步钩子",
        ]
        text = "\n".join(str(plan.get(field) or "") for field in ["objective", "plot_summary", "unique_task", "core_event"])
        if not str(plan.get("core_event") or "").strip() or any(item in text for item in blocked):
            raise ValueError("chapter_plan_not_ready")

    def _finalize_decision(self, book_id: int, chapter_no: int, draft: dict, decision: dict) -> dict[str, object]:
        report = decision.get("report") or self._decision_payload(decision)
        status = str(report.get("status") or decision.get("decision") or "")
        if status == "approved":
            plan = self.repo.get_chapter_plan(book_id, chapter_no)
            title = plan.title if plan else f"Chapter {chapter_no}"
            self.repo.save_chapter_body(book_id, chapter_no, title, str(draft.get("content") or ""), status="editor_approved")
            self.repo.set_chapter_task_status(book_id, chapter_no, "editorial_passed")
        else:
            self.repo.set_chapter_task_status(book_id, chapter_no, "rewrite_needed")
        failure_code = ",".join(report.get("failure_codes") or [])
        return {"status": status, "failure_code": failure_code, "review_data": report}

    def _decision_payload(self, decision: dict) -> dict:
        try:
            return {
                "status": decision.get("decision"),
                "failure_codes": [code for code in str(decision.get("failure_code") or "").split(",") if code],
                "evidence": json.loads(decision.get("evidence") or "[]"),
                "required_fixes": json.loads(decision.get("required_fixes") or "[]"),
                "route": decision.get("route"),
                "score": decision.get("score"),
            }
        except Exception:
            return {"status": decision.get("decision"), "failure_codes": [], "evidence": [], "required_fixes": []}

    def rewrite_and_review(self, book_id: int, chapter_no: int) -> dict[str, object]:
        ticket = self.repo.get_rework_ticket(book_id, chapter_no)
        if not ticket:
            return self.generate_chapter(book_id, chapter_no)
        attempts = int(ticket.get("attempts") or 0)
        max_attempts = int(ticket.get("max_attempts") or 2)
        if attempts >= max_attempts:
            self.repo.update_rework_ticket(int(ticket["id"]), "manual_required", attempts)
            return {"status": "manual_required", "ticket": ticket}
        self.repo.update_rework_ticket(int(ticket["id"]), "running", attempts + 1)
        feedback = str(ticket.get("required_fixes") or "")
        result = self.generate_chapter(book_id, chapter_no, feedback)
        if result.get("status") == "approved":
            self.repo.update_rework_ticket(int(ticket["id"]), "fixed", attempts + 1)
        elif attempts + 1 >= max_attempts:
            self.repo.update_rework_ticket(int(ticket["id"]), "manual_required", attempts + 1)
        else:
            self.repo.update_rework_ticket(int(ticket["id"]), "open", attempts + 1)
        return result

    def generate_batch(self, book_id: int, batch_id: int) -> list[dict[str, object]]:
        batch = self.repo.get_chapter_batch(batch_id)
        if not batch:
            raise ValueError("chapter_batch_missing")
        self.repo.update_batch_status(batch_id, "running", "开始按 active chapter 状态机生成正文。", "")
        results = []
        for plan in self.repo.list_chapter_plan_rows(book_id, batch_id):
            chapter_no = int(plan["chapter_no"])
            self.repo.update_batch_status(batch_id, "running", f"正在生成第 {chapter_no} 章：{plan['title']}", "")
            result = self.generate_chapter(book_id, chapter_no)
            if result.get("status") == "rejected":
                for _ in range(2):
                    result = self.rewrite_and_review(book_id, chapter_no)
                    if result.get("status") == "approved":
                        break
            results.append(result)
            if result.get("status") != "approved":
                reason = self._result_failure_reason(result)
                self.repo.update_batch_status(batch_id, "waiting_previous_fix", f"第 {chapter_no} 章未通过，后续章节等待本章修复。", f"stopped_on_chapter={chapter_no}; {reason}")
                return results
            if chapter_no < int(batch["end_chapter"]):
                self.repo.update_batch_status(batch_id, "waiting_previous_fix", f"第 {chapter_no} 章已编辑通过。请人工确认并导出/发布后，再让下一章进入 drafting。", f"stopped_on_chapter={chapter_no}; waiting_for_publish")
                return results
        self.repo.update_batch_status(batch_id, "linear_completed", "线性生成完成，等待人工确认和发布。", "")
        return results

    def generate_next_three(self, book_id: int) -> list[dict[str, object]]:
        batch_id = self.repo.create_chapter_batch(book_id, 3)
        self.plan_batch(book_id, batch_id)
        return self.generate_batch(book_id, batch_id)

    def _result_failure_reason(self, result: dict[str, object]) -> str:
        if result.get("error"):
            return str(result["error"])[:800]
        review_data = result.get("review_data")
        if isinstance(review_data, dict):
            problems = review_data.get("evidence") or review_data.get("problems") or []
            if isinstance(problems, list) and problems:
                return "；".join(str(item) for item in problems[:5])[:800]
        return f"status={result.get('status')}"

    def manual_approve(self, book_id: int, chapter_no: int) -> dict[str, object]:
        body = self.repo.get_chapter_body(book_id, chapter_no)
        if not body:
            draft = self.repo.latest_chapter_draft(book_id, chapter_no)
            if draft is None:
                raise ValueError("no draft to approve")
            plan = self.repo.get_chapter_plan(book_id, chapter_no)
            self.repo.save_chapter_body(book_id, chapter_no, plan.title if plan else f"Chapter {chapter_no}", str(draft.get("content") or ""), "human_confirmed")
        else:
            self.repo.confirm_chapter_body(book_id, chapter_no)
        return {"status": "human_confirmed"}
