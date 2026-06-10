from __future__ import annotations

from typing import Any

from app.llm import LlmClient, TextGuard
from app.services.continuity_studio import ContinuityLedgerService
from app.services.editorial_department import EditorialDepartment
from app.services.planning_agent import PlanningAgent
from app.services.writing_department import WritingDepartment
from app.storage.repository import Repository, json_safe


class WorkflowKernel:
    """Database-backed workflow coordinator for the rebuilt main path.

    Batches and artifacts can still be displayed as history, but this object is
    the only official route for planning, drafting, review, rework, and publish.
    """

    def __init__(self, repo: Repository, llm: LlmClient):
        self.repo = repo
        self.llm = llm
        self.planner = PlanningAgent(repo, llm)
        self.continuity = ContinuityLedgerService(repo)
        self.writer = WritingDepartment(repo, llm)
        self.editor = EditorialDepartment(repo, TextGuard())

    def create_book_flow(self, **kwargs: Any) -> int:
        book_id = self.repo.create_book(**kwargs)
        run = self.repo.create_workflow_run(book_id, "create_book_flow", payload={"title": kwargs.get("title")})
        self.repo.update_workflow_run(int(run["id"]), "completed", "book_created", 100, payload={"book_id": book_id})
        return book_id

    def plan_next_chapter_flow(
        self,
        book_id: int,
        count: int = 1,
        volume_id: int | None = None,
        arc_id: int | None = None,
    ) -> dict[str, Any]:
        count = max(1, min(int(count or 1), 20))
        run = self.repo.create_workflow_run(
            book_id,
            "plan_next_chapter_flow",
            payload={"count": count, "volume_id": volume_id, "arc_id": arc_id},
        )
        run_id = int(run["id"])
        try:
            batch_id = self.repo.create_chapter_batch(book_id, count, volume_id, arc_id)
            self.repo.create_workflow_event(
                run_id,
                book_id,
                None,
                "candidate_window_created",
                f"已创建 {count} 个候选章节窗口。",
                {"batch_id": batch_id},
            )
            planned = self.planner.plan_chapter_batch(book_id, batch_id)
            candidates = []
            for item in planned:
                errors = self.validate_chapter_work_order(item)
                candidate = self.repo.upsert_chapter_candidate(
                    book_id,
                    int(item["chapter_no"]),
                    self._work_order_from_plan(item),
                    volume_id=item.get("volume_id") or volume_id,
                    arc_id=item.get("arc_id") or arc_id,
                    status="invalid" if errors else "candidate",
                    validation_errors=errors,
                )
                candidates.append(candidate)
            self.repo.update_workflow_run(
                run_id,
                "completed",
                "candidates_ready",
                100,
                payload={"batch_id": batch_id, "candidate_count": len(candidates)},
            )
            return {"status": "completed", "run_id": run_id, "batch_id": batch_id, "candidates": candidates}
        except Exception as exc:
            self.repo.update_workflow_run(run_id, "failed", "planning_failed", 100, str(exc), {"error": str(exc)})
            raise

    def draft_next_chapter_flow(self, book_id: int, chapter_no: int | None = None, rewrite_feedback: str = "") -> dict[str, Any]:
        chapter_no = chapter_no or self._next_candidate_or_chapter(book_id)
        run = self.repo.create_workflow_run(book_id, "draft_next_chapter_flow", chapter_no, {"rewrite": bool(rewrite_feedback)})
        run_id = int(run["id"])
        try:
            task = self._task_for_drafting(book_id, chapter_no)
            self.repo.assert_can_enter_drafting(book_id, chapter_no)
            self.repo.set_chapter_task_status(book_id, chapter_no, "drafting")
            self.repo.create_workflow_event(
                run_id,
                book_id,
                chapter_no,
                "drafting_started",
                "施工包生成中。",
                {"task_id": task.get("id")},
            )
            packet = self.continuity.build_construction_packet(book_id, chapter_no, run_id)
            draft = self.writer.draft_from_packet(book_id, chapter_no, packet, rewrite_feedback)
            self.repo.set_chapter_task_status(book_id, chapter_no, "editorial_review")
            decision = self.editor.review_draft(book_id, chapter_no, draft, run_id)
            result = self._finish_editorial_step(book_id, chapter_no, draft, decision, run_id)
            return {"run_id": run_id, "chapter_no": chapter_no, "task": task, "draft": draft, "decision": decision, **result}
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self.repo.update_workflow_run(run_id, "failed", "draft_failed", 100, message, {"error": message})
            try:
                self.repo.set_chapter_task_status(book_id, chapter_no, "rewrite_needed")
            except Exception:
                pass
            return {"status": "failed", "run_id": run_id, "chapter_no": chapter_no, "error": message, "failure_code": "runtime_error"}

    def review_next_chapter_flow(self, book_id: int, chapter_no: int) -> dict[str, Any]:
        draft = self.repo.latest_chapter_draft(book_id, chapter_no)
        if not draft:
            raise ValueError("chapter_draft_missing")
        run = self.repo.create_workflow_run(book_id, "review_next_chapter_flow", chapter_no)
        decision = self.editor.review_draft(book_id, chapter_no, draft, int(run["id"]))
        status = "completed" if decision.get("decision") == "approved" else "blocked"
        self.repo.update_workflow_run(int(run["id"]), status, "reviewed", 100, payload={"decision_id": decision.get("id")})
        return {"run_id": int(run["id"]), "decision": decision}

    def rework_flow(self, book_id: int, chapter_no: int) -> dict[str, Any]:
        ticket = self.repo.get_rework_ticket(book_id, chapter_no)
        if not ticket:
            return self.draft_next_chapter_flow(book_id, chapter_no)
        attempts = int(ticket.get("attempts") or 0)
        max_attempts = int(ticket.get("max_attempts") or 2)
        if attempts >= max_attempts:
            self.repo.update_rework_ticket(int(ticket["id"]), "manual_required", attempts)
            return {"status": "manual_required", "ticket": ticket}
        self.repo.update_rework_ticket(int(ticket["id"]), "running", attempts + 1)
        result = self.draft_next_chapter_flow(book_id, chapter_no, str(ticket.get("required_fixes") or ""))
        next_status = "fixed" if result.get("status") == "approved" else ("manual_required" if attempts + 1 >= max_attempts else "open")
        self.repo.update_rework_ticket(int(ticket["id"]), next_status, attempts + 1)
        return result

    def publish_flow(self, book_id: int, export_id: int | None = None) -> dict[str, Any]:
        run = self.repo.create_workflow_run(book_id, "publish_flow", payload={"export_id": export_id})
        run_id = int(run["id"])
        try:
            if export_id is None:
                record = self.repo.create_export_record(book_id, "internal_publish", "")
                export_id = int(record["id"])
            self.repo.mark_exported(book_id, export_id)
            self.continuity.writeback_from_export(book_id, export_id)
            self.repo.update_workflow_run(run_id, "completed", "published", 100, payload={"export_id": export_id})
            return {"status": "published", "run_id": run_id, "export_id": export_id}
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self.repo.update_workflow_run(run_id, "failed", "publish_failed", 100, message, {"error": message})
            raise

    def validate_chapter_work_order(self, item: dict[str, Any]) -> list[str]:
        text = self._json_text(item)
        required = ["chapter_no", "title", "unique_task", "core_event", "irreversible_change", "ending_hook"]
        errors = [f"缺少 {field}" for field in required if not str(item.get(field) or "").strip()]
        banned = [
            "承接单元起因，推进经过，并为结果兑现蓄力",
            "本章留下下一步钩子",
            "待规划",
            "技术突破词条",
        ]
        errors.extend([f"包含模板/污染句：{phrase}" for phrase in banned if phrase in text])
        return errors

    def _finish_editorial_step(self, book_id: int, chapter_no: int, draft: dict[str, Any], decision: dict[str, Any], run_id: int) -> dict[str, Any]:
        report = decision.get("report") or {}
        status = str(report.get("status") or decision.get("decision") or "")
        if status == "approved":
            plan = self.repo.get_chapter_plan(book_id, chapter_no)
            title = plan.title if plan else f"第{chapter_no}章"
            self.repo.save_chapter_body(book_id, chapter_no, title, str(draft.get("content") or ""), "editor_approved")
            self.repo.set_chapter_task_status(book_id, chapter_no, "editorial_passed")
            self.repo.update_workflow_run(run_id, "completed", "editorial_passed", 100, payload={"decision_id": decision.get("id")})
        else:
            self.repo.set_chapter_task_status(book_id, chapter_no, "rewrite_needed")
            self.repo.update_workflow_run(run_id, "blocked", "rewrite_needed", 100, payload={"decision_id": decision.get("id"), "route": report.get("route")})
        return {
            "status": status,
            "failure_code": ",".join(report.get("failure_codes") or []),
            "review_data": report,
        }

    def _task_for_drafting(self, book_id: int, chapter_no: int) -> dict[str, Any]:
        candidate = self.repo.get_chapter_candidate(book_id, chapter_no)
        if candidate:
            task = self.repo.promote_candidate_to_task(book_id, chapter_no)
            self.repo.update_chapter_candidate_status(book_id, chapter_no, "promoted")
            return task
        return self.repo.ensure_chapter_task(book_id, chapter_no)

    def _work_order_from_plan(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "chapter_no": item.get("chapter_no"),
            "title": item.get("title"),
            "opening_state": item.get("pace_limit", ""),
            "mission": item.get("unique_task") or item.get("objective", ""),
            "core_event": item.get("core_event", ""),
            "scene_route": item.get("plot_summary", ""),
            "progression": item.get("tech_progression", ""),
            "character_roles": item.get("character_roles", ""),
            "antagonist_move": item.get("antagonist_move", ""),
            "external_pressure": item.get("external_pressure", ""),
            "irreversible_change": item.get("irreversible_change", ""),
            "handoff_to_next": item.get("ending_hook", ""),
            "forbidden_future": item.get("forbidden_reveals", ""),
            "no_repeat_guard": item.get("no_repeat_guard", ""),
            "allowed_reveals": item.get("allowed_reveals", ""),
            "target_chars": item.get("target_chars") or 2600,
        }

    def _next_candidate_or_chapter(self, book_id: int) -> int:
        candidates = self.repo.list_chapter_candidates(book_id, status="candidate", limit=1)
        if candidates:
            return int(candidates[0]["chapter_no"])
        bodies = self.repo.list_chapter_bodies(book_id)
        return int(bodies[-1]["chapter_no"]) + 1 if bodies else 1

    def _json_text(self, value: Any) -> str:
        import json

        return json.dumps(json_safe(value), ensure_ascii=False)
