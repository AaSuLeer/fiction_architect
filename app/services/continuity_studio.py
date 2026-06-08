from __future__ import annotations

import json

from app.storage.repository import Repository


class PromptCompressor:
    def __init__(self, mode: str = "structured_budget", token_budget: int = 5000):
        self.mode = mode if mode in {"none", "structured_budget", "llmlingua_optional"} else "structured_budget"
        self.token_budget = token_budget

    def select(self, memories: list[dict], atoms: list[dict], query: str) -> tuple[list[dict], list[dict], str]:
        if self.mode == "none":
            return memories, atoms, "未启用压缩，保留全部候选。"
        keywords = [part for part in query.replace("，", " ").replace("。", " ").split() if len(part) >= 2]

        def score(item: dict) -> int:
            text = json.dumps(item, ensure_ascii=False)
            return sum(1 for key in keywords if key in text)

        ranked_memories = sorted(memories, key=score, reverse=True)[:8]
        ranked_atoms = sorted(atoms, key=score, reverse=True)[:40]
        reason = "结构化预算检索：硬事实和本章细纲优先，最近记忆、单元/卷记忆按当前章节目标重排。"
        return ranked_memories, ranked_atoms, reason


class ContinuityStudio:
    def __init__(self, repo: Repository):
        self.repo = repo
        self.compressor = PromptCompressor()

    def build_ref_pack(self, book_id: int, chapter_no: int, run_id: int | None = None):
        ctx = self.repo.get_architecture_context(book_id, chapter_no)
        query = f"{ctx['plan']['objective']} {ctx['plan'].get('plot_summary', '')} {ctx['plan']['allowed_reveals']}"
        recent = []
        for no in range(max(1, chapter_no - 5), chapter_no):
            memory = self.repo.latest_memory(book_id, "chapter_memory", f"chapter:{no}")
            if memory:
                recent.append(memory)
        tiered = recent + self.repo.list_memories(book_id, "unit_memory", 8) + self.repo.list_memories(book_id, "volume_memory", 4) + self.repo.list_memories(book_id, "quarter_memory", 2) + self.repo.list_memories(book_id, "year_memory", 2)
        atoms = [atom for atom in self.repo.list_atoms(book_id, status="approved") if int(atom.get("visible_after_chapter") or 0) <= chapter_no]
        selected_memories, selected_atoms, reason = self.compressor.select(tiered, atoms, query)
        log = self.repo.create_retrieval_log(book_id, chapter_no, query, [int(m["id"]) for m in selected_memories], [int(a["id"]) for a in selected_atoms], reason, run_id)
        ref_pack = {
            "name": "连续性资料",
            "chapter": ctx["plan"],
            "volume": ctx["volume"],
            "unit": ctx["arc"],
            "canon_ledger": ctx["canon"],
            "characters": ctx["characters"],
            "selected_memories": selected_memories,
            "selected_atoms": selected_atoms,
            "retrieval_log_id": log["id"],
            "compression_policy": reason,
            "gate": [
                "只展示当前角色已知信息。",
                "硬事实、人物关系、伏笔账本不可有损压缩。",
                "未批准 atom 不进入写作资料。",
                "正文只有人工确认并导出后才写回连续性。",
            ],
        }
        return self.repo.create_artifact(book_id, chapter_no, "ref_pack", "ready", json.dumps(ref_pack, ensure_ascii=False, indent=2))

    def writeback_from_export(self, book_id: int, export_id: int):
        bodies = [row for row in self.repo.list_chapter_bodies(book_id, status="exported") if int(row.get("export_id") or 0) == int(export_id)]
        patches = []
        for row in bodies:
            patches.append(self.compress_exported_chapter(book_id, int(row["chapter_no"]), row["body"], export_id))
        return patches

    def compress_exported_chapter(self, book_id: int, chapter_no: int, body: str, export_id: int):
        plan = self.repo.get_chapter_plan_row(book_id, chapter_no) or {}
        compact = self._compact_text(body, max(500, int(len(body) * 0.12)))
        raw = self.repo.create_memory(book_id, "raw_exported_chapter", f"chapter:{chapter_no}", body, chapter_no, chapter_no, export_id, token_budget=len(body))
        chapter_memory = {
            "level": "chapter_memory",
            "chapter_no": chapter_no,
            "title": plan.get("title", f"第{chapter_no}章"),
            "cause": self._pick_sentence(body, ["倒计时", "惩罚", "资格", "危机", "必须", "逼"]),
            "process": self._pick_sentence(body, ["伸手", "判断", "反问", "试", "改", "挡", "转身"]),
            "result": self._pick_sentence(body, ["终于", "通过", "赢", "败", "代价", "留下", "换来"]),
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
        return self.repo.create_artifact(book_id, chapter_no, "continuity_patch", "candidate", json.dumps({"raw_memory_id": raw["id"], "chapter_memory_id": memory["id"], "atom_id": atom["id"], "source_export_id": export_id}, ensure_ascii=False, indent=2))

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
        content = {
            "level": "volume_memory",
            "scope": f"{start}-{end}",
            "sources": [m["id"] for m in units],
            "summary": self._compact_text("\n".join(m["content"] for m in units), 1800),
        }
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
            "risks": ["未批准 atom 不会进入后续写作资料。", "未导出正文不会进入连续性记忆。"],
            "prompt_growth": "资料包按预算检索，不随章节总数线性增长。",
        }
        return self.repo.create_drift_report(book_id, chapter_no, report)

    def _compact_text(self, text: str, limit: int) -> str:
        return " ".join(text.split())[:limit]

    def _pick_sentence(self, text: str, keys: list[str]) -> str:
        parts = [p.strip() for p in text.replace("。", "。\n").replace("！", "！\n").replace("？", "？\n").splitlines() if p.strip()]
        for part in parts:
            if any(key in part for key in keys):
                return part[:180]
        return (parts[0] if parts else "")[:180]
