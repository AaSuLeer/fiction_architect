from __future__ import annotations

import json

from app.storage.repository import Repository, json_safe


class PromptCompressor:
    def __init__(self, mode: str = "structured_budget", token_budget: int = 5000):
        self.mode = mode if mode in {"none", "structured_budget", "llmlingua_optional"} else "structured_budget"
        self.token_budget = token_budget

    def select(self, memories: list[dict], atoms: list[dict], query: str) -> tuple[list[dict], list[dict], str]:
        if self.mode == "none":
            return memories, atoms, "未启用压缩，保留全部候选。"
        keywords = [part for part in query.replace("；", " ").replace("。", " ").split() if len(part) >= 2]

        def score(item: dict) -> int:
            text = json.dumps(item, ensure_ascii=False)
            return sum(1 for key in keywords if key in text)

        ranked_memories = sorted(memories, key=score, reverse=True)[:6]
        ranked_atoms = sorted(atoms, key=score, reverse=True)[:24]
        reason = "结构化预算检索：全书/卷/单元/章节纲要优先，最近章节记忆和相关 atom 按当前章节目标重排。"
        return ranked_memories, ranked_atoms, reason


class ContinuityLedgerService:
    def __init__(self, repo: Repository):
        self.repo = repo
        self.compressor = PromptCompressor()

    def build_construction_packet(self, book_id: int, chapter_no: int, run_id: int | None = None) -> dict:
        ctx = self.repo.get_architecture_context(book_id, chapter_no)
        book = ctx["book"]
        plan = ctx["plan"]
        volume = ctx["volume"] or {}
        unit = ctx["arc"] or {}
        task = self.repo.ensure_chapter_task(book_id, chapter_no)
        recent_transitions = self.repo.list_recent_transitions(book_id, chapter_no, 3)
        recent_snapshots = [
            row for row in self.repo.list_snapshots(book_id, 20)
            if int(row.get("chapter_no") or 0) < int(chapter_no)
        ][:3]
        previous_context = self._previous_chapter_context(book_id, chapter_no, formal_only=True)
        atoms = [
            atom for atom in self.repo.list_atoms(book_id)
            if str(atom.get("status") or "") in {"approved", "published"}
            and int(atom.get("visible_after_chapter") or 0) <= chapter_no
        ][:24]
        ledger_candidates = [
            item for item in self.repo.list_ledger_candidates(book_id, status="approved", limit=50)
        ][:24]
        query = " ".join(
            [
                str(task.get("mission") or ""),
                str(plan.get("plot_summary") or ""),
                str(unit.get("goal") or ""),
                str(volume.get("goal") or ""),
            ]
        )
        log = self.repo.create_retrieval_log(
            book_id,
            chapter_no,
            query,
            [int(row["id"]) for row in recent_snapshots],
            [int(a["id"]) for a in atoms],
            "construction_packet_v2: published snapshots/transitions, approved/published atoms, current task, current unit state, style pack.",
            run_id,
        )
        packet = {
            "chapter_task": json_safe(task),
            "recent_transitions": json_safe(recent_transitions),
            "recent_snapshots": json_safe(recent_snapshots),
            "active_unit_state": {
                "book_outline": book.get("book_outline") or book.get("imported_outline") or book.get("story_mainline") or "",
                "volume": volume,
                "unit": unit,
                "chapter_plan": plan,
            },
            "on_stage_cast": ctx["characters"],
            "hard_constraints": {
                "pov_policy": book.get("pov_policy") or "third_limited",
                "official_canon": self.repo.list_official_canon(book_id, 40),
                "ledger_updates": ledger_candidates,
                "approved_atoms": [self._atom_prompt_view(item) for item in atoms],
                "visibility_rule": "Only approved/published facts visible for this chapter may be used.",
            },
            "style_pack": ctx.get("author_profile") or {},
            "optional_prev_excerpt": previous_context["body_excerpt"],
            "previous_terminal_state": previous_context["terminal_state"],
            "retrieval_log_id": log["id"],
            "retrieval_reason": "construction_packet_v2 only reads published/canonized prior text, approved/published atoms, current task, current outline state, and style pack.",
        }
        return self.repo.create_construction_packet(book_id, chapter_no, run_id, packet)

    def build_ref_pack(self, book_id: int, chapter_no: int, run_id: int | None = None):
        ctx = self.repo.get_architecture_context(book_id, chapter_no)
        book = ctx["book"]
        plan = ctx["plan"]
        volume = ctx["volume"] or {}
        unit = ctx["arc"] or {}
        query = " ".join(
            [
                str(plan.get("objective", "")),
                str(plan.get("plot_summary", "")),
                str(unit.get("goal", "")),
                str(volume.get("goal", "")),
            ]
        )
        recent = []
        for no in range(max(1, chapter_no - 5), chapter_no):
            memory = self.repo.latest_memory(book_id, "chapter_memory", f"chapter:{no}")
            if memory:
                recent.append(memory)
        tiered = recent + self.repo.list_memories(book_id, "unit_memory", 8) + self.repo.list_memories(book_id, "volume_memory", 4) + self.repo.list_memories(book_id, "quarter_memory", 2) + self.repo.list_memories(book_id, "year_memory", 2)
        atoms = [atom for atom in self.repo.list_atoms(book_id, status="approved") if int(atom.get("visible_after_chapter") or 0) <= chapter_no]
        selected_memories, selected_atoms, reason = self.compressor.select(tiered, atoms, query)
        previous_context = self._previous_chapter_context(book_id, chapter_no)
        function_history = self._function_history(book_id, chapter_no)
        log = self.repo.create_retrieval_log(book_id, chapter_no, query, [int(m["id"]) for m in selected_memories], [int(a["id"]) for a in selected_atoms], reason, run_id)
        ref_pack = {
            "name": "连续性资料",
            "outline_stack": {
                "book_outline": book.get("book_outline") or book.get("imported_outline") or book.get("story_mainline") or "",
                "volume": volume,
                "unit": unit,
                "chapter": plan,
            },
            "canon_ledger": ctx["canon"],
            "characters": ctx["characters"],
            "previous_chapter_body": previous_context["body_excerpt"],
            "previous_chapter_terminal_state": previous_context["terminal_state"],
            "completed_function_history": function_history["completed"],
            "forbidden_repetition": function_history["forbidden_repetition"],
            "temporary_linear_context": previous_context["temporary_linear_context"],
            "selected_memories": [self._memory_prompt_view(item) for item in selected_memories],
            "selected_atoms": [self._atom_prompt_view(item) for item in selected_atoms],
            "retrieval_log_id": log["id"],
            "compression_policy": reason,
            "gate": [
                "只展示当前角色已知信息。",
                "硬事实、人物关系、伏笔账本不可有损压缩。",
                "未批准 atom 不进入写作资料。",
                "正文只有人工确认并导出后才写回连续性。",
            ],
        }
        return self.repo.create_artifact(book_id, chapter_no, "ref_pack", "ready", json.dumps(json_safe(ref_pack), ensure_ascii=False, indent=2))

    def _previous_chapter_context(self, book_id: int, chapter_no: int, formal_only: bool = False) -> dict:
        if chapter_no <= 1:
            return {"body_excerpt": "", "terminal_state": "首章无上一章正文。", "temporary_linear_context": ""}
        previous = self.repo.get_chapter_body(book_id, chapter_no - 1)
        if not previous:
            draft = None if formal_only else self.repo.latest_artifact(book_id, chapter_no - 1, "draft")
            body = draft.content if draft and draft.status in {"editor_approved", "drafted"} else ""
            status = draft.status if draft else "missing"
        else:
            status = previous.get("status") or ""
            body = previous.get("body") or "" if (not formal_only or status in {"exported", "published", "canonized"}) else ""
        excerpt = self._body_excerpt(body, 5600)
        tail = self._compact_text(body, 900)
        return {
            "body_excerpt": excerpt,
            "terminal_state": f"上一章状态：{status}；结尾状态节选：{tail}",
            "temporary_linear_context": "该内容用于本批次线性续写；只有人工确认并导出后才写回正式连续性。",
        }

    def _body_excerpt(self, body: str, limit: int) -> str:
        compact = " ".join((body or "").split())
        if len(compact) <= limit:
            return compact
        head = compact[:1800]
        middle_start = max(1800, len(compact) // 2 - 900)
        middle = compact[middle_start:middle_start + 1800]
        tail = compact[-1600:]
        return f"{head}\n...\n{middle}\n...\n{tail}"

    def _function_history(self, book_id: int, chapter_no: int) -> dict:
        start = max(1, chapter_no - 5)
        rows = [self.repo.get_chapter_plan_row(book_id, no) for no in range(start, chapter_no)]
        rows = [row for row in rows if row]
        completed = []
        forbidden = []
        for row in rows:
            completed.append(
                {
                    "chapter_no": row.get("chapter_no"),
                    "unique_task": row.get("unique_task") or row.get("objective", ""),
                    "core_event": row.get("core_event") or "",
                    "tech_progression": row.get("tech_progression") or "",
                    "irreversible_change": row.get("irreversible_change") or "",
                    "ending_hook": row.get("ending_hook") or "",
                }
            )
            guard = row.get("no_repeat_guard") or row.get("core_event") or row.get("unique_task") or ""
            if guard:
                forbidden.append(f"不要重复第 {row.get('chapter_no')} 章：{guard}")
        return {"completed": completed, "forbidden_repetition": forbidden}

    def _memory_prompt_view(self, memory: dict) -> dict:
        content = str(memory.get("content") or "")
        budget = min(900, max(300, int(memory.get("token_budget") or 700)))
        return {
            "id": memory.get("id"),
            "memory_type": memory.get("memory_type"),
            "scope_key": memory.get("scope_key"),
            "version": memory.get("version"),
            "chapter_range": [memory.get("source_start_chapter"), memory.get("source_end_chapter")],
            "source_export_id": memory.get("source_export_id"),
            "content": self._compact_text(content, budget),
        }

    def _atom_prompt_view(self, atom: dict) -> dict:
        return {
            "id": atom.get("id"),
            "atom_type": atom.get("atom_type"),
            "chapter_no": atom.get("chapter_no"),
            "visible_after_chapter": atom.get("visible_after_chapter"),
            "confidence": atom.get("confidence"),
            "content": self._compact_text(str(atom.get("content") or ""), 360),
        }

    def writeback_from_export(self, book_id: int, export_id: int):
        bodies = [row for row in self.repo.list_chapter_bodies(book_id, status="exported") if int(row.get("export_id") or 0) == int(export_id)]
        self.repo.backfill_phase2_ledgers(book_id)
        for row in bodies:
            chapter_no = int(row["chapter_no"])
            if not self.repo.latest_memory(book_id, "chapter_memory", f"chapter:{chapter_no}"):
                compact = self._compact_text(str(row.get("body") or ""), 1200)
                self.repo.create_memory(
                    book_id,
                    "chapter_memory",
                    f"chapter:{chapter_no}",
                    {"archival": True, "source": f"export:{export_id}", "summary": compact},
                    chapter_no,
                    chapter_no,
                    export_id,
                )
        return self.repo.list_ledger_candidates(book_id, limit=50)

    def compress_exported_chapter(self, book_id: int, chapter_no: int, body: str, export_id: int):
        plan = self.repo.get_chapter_plan_row(book_id, chapter_no) or {}
        compact = self._compact_text(body, max(500, int(len(body) * 0.12)))
        raw = self.repo.create_memory(book_id, "raw_exported_chapter", f"chapter:{chapter_no}", body, chapter_no, chapter_no, export_id, token_budget=len(body))
        chapter_memory = {
            "level": "chapter_memory",
            "chapter_no": chapter_no,
            "title": plan.get("title", f"第{chapter_no}章"),
            "volume": plan.get("volume_title", ""),
            "unit": plan.get("arc_title", ""),
            "summary_5_15_percent": compact,
            "source": f"export:{export_id}",
        }
        memory = self.repo.create_memory(book_id, "chapter_memory", f"chapter:{chapter_no}", chapter_memory, chapter_no, chapter_no, export_id)
        atom = self.repo.create_atom(
            book_id,
            chapter_no,
            "chapter_fact",
            f"第 {chapter_no} 章导出正文确认：{compact[:180]}",
            status="candidate",
            visible_after_chapter=chapter_no,
            source_ref=f"export:{export_id}",
            source_export_id=export_id,
            confidence=0.75,
        )
        if chapter_no % 3 == 0:
            self.compress_unit(book_id, chapter_no - 2, chapter_no, export_id)
        if chapter_no % 50 == 0:
            self.compress_volume(book_id, chapter_no - 49, chapter_no, export_id)
        self.repo.set_chapter_task_status(book_id, chapter_no, "canonized")
        return self.repo.create_artifact(book_id, chapter_no, "continuity_patch", "candidate", json.dumps(json_safe({"raw_memory_id": raw["id"], "chapter_memory_id": memory["id"], "atom_id": atom["id"], "source_export_id": export_id}), ensure_ascii=False, indent=2))

    def compress_unit(self, book_id: int, start: int, end: int, export_id: int | None = None):
        memories = [self.repo.latest_memory(book_id, "chapter_memory", f"chapter:{no}") for no in range(start, end + 1)]
        packed = [m for m in memories if m]
        content = {
            "level": "unit_memory",
            "scope": f"{start}-{end}",
            "sources": [m["id"] for m in packed],
            "summary": self._compact_text("\n".join(m["content"] for m in packed), 1200),
            "open_threads": "保留未兑现代价、下一单元钩子、未批准 atom。",
        }
        return self.repo.create_memory(book_id, "unit_memory", f"unit:auto:{start}-{end}", content, start, end, export_id)

    def compress_volume(self, book_id: int, start: int, end: int, export_id: int | None = None):
        units = self.repo.list_memories(book_id, "unit_memory", 30)
        content = {"level": "volume_memory", "scope": f"{start}-{end}", "sources": [m["id"] for m in units], "summary": self._compact_text("\n".join(m["content"] for m in units), 1800)}
        return self.repo.create_memory(book_id, "volume_memory", f"volume:auto:{start}-{end}", content, start, end, export_id)

    def compress_period(self, book_id: int, memory_type: str):
        if memory_type not in {"quarter_memory", "year_memory"}:
            raise ValueError("period memory must be quarter_memory or year_memory")
        source = self.repo.list_memories(book_id, "volume_memory", 12)
        content = {"level": memory_type, "sources": [m["id"] for m in source], "summary": self._compact_text("\n".join(m["content"] for m in source), 2200)}
        return self.repo.create_memory(book_id, memory_type, "current", content)

    def drift_check(self, book_id: int, chapter_no: int | None = None):
        report = {
            "name": "连续性漂移报告",
            "chapter_no": chapter_no,
            "risks": ["未批准 atom 不会进入后续写作资料。", "未导出正文不会进入连续性记忆。", "章节必须服从全书大纲、卷纲、单元纲和章节细纲。"],
            "prompt_growth": "资料包按预算检索，不随章节总数线性增长。",
        }
        return self.repo.create_drift_report(book_id, chapter_no, report)

    def _compact_text(self, text: str, limit: int) -> str:
        return " ".join(text.split())[:limit]


ContinuityStudio = ContinuityLedgerService
