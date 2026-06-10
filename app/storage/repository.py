from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timezone
from typing import Any

from app.domain import Artifact, Book, ChapterPlan
from app.storage.database import Database


POV_LABELS = {
    "third_limited": "第三人称有限视角",
    "first_person": "第一人称主角视角",
    "third_omniscient": "第三人称全知视角",
}

ARTIFACT_LABELS = {
    "author_brief": "本章写作任务",
    "ref_pack": "连续性资料",
    "draft": "正文草稿",
    "review": "编辑意见",
    "continuity_patch": "连续性更新建议",
    "generation_error": "生成失败原因",
    "planning_backup": "旧规划备份",
}

DEFAULT_AUTHOR = {
    "name": "默认商业男频作者",
    "genre": "中国网文男频爽文",
    "pov_preference": "third_limited",
    "sentence_rhythm": "短句、中句、少量长句自然混合；动作句推进，心理句收束。",
    "dialogue_style": "对白短促，有试探和反击，避免解释设定。",
    "payoff_preference": "压力、判断、反击、小兑现、代价或新钩子。",
    "forbidden_items": "部门话术；说明书式世界观；整段设定；机械打脸。",
    "prompt_rules": "正文只写小说文本。设定通过行动、证据、惩罚、交易、对白露出。",
}

DEFAULT_EDITOR = {
    "name": "默认番茄男频编辑",
    "platform": "番茄/男频",
    "word_count_rule": "目标 2200-3200 字；低于最低字数拒稿，高于上限 600 字以上提示失控。",
    "pov_rule": "人称以作品设置为准；第一人称作品不因第一人称拒稿。",
    "structure_rule": "必须有起因、经过、结果；首屏有压力，中段有行动和反应，末尾有兑现或代价。",
    "payoff_rule": "爽点来自行动和局势变化，不允许通篇机械打脸，也不能没有爽点。",
    "pollution_rule": "正文不得出现交付、审稿、根据规则、连续性工作室、比上一章更稳等部门话术。",
    "reject_threshold": 1,
}


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def safe_int_field(value: Any, default: int, minimum: int | None = None, maximum: int | None = None, field_name: str = "value") -> int:
    if value is None:
        number = default
    else:
        text = str(value).strip()
        if not text:
            number = default
        else:
            text = text.replace(",", "").replace("_", "")
            multipliers = {"万": 10000, "千": 1000, "k": 1000, "K": 1000}
            multiplier = 1
            if text[-1:] in multipliers:
                multiplier = multipliers[text[-1]]
                text = text[:-1].strip()
            try:
                number = int(float(text) * multiplier)
            except ValueError as exc:
                raise ValueError(f"{field_name} must be a number.") from exc
    if minimum is not None and number < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}.")
    if maximum is not None and number > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}.")
    return number


def normalize_word_targets(target_min: Any, target_max: Any, total_words: Any) -> tuple[int, int, int]:
    min_chars = safe_int_field(target_min, 2200, 1, 30000, "target_chars_min")
    max_chars = safe_int_field(target_max, 3200, min_chars, 50000, "target_chars_max")
    if max_chars < min_chars:
        raise ValueError("target_chars_max must be greater than or equal to target_chars_min.")
    estimated = safe_int_field(total_words, 1000000, 100000, 50000000, "estimated_total_words")
    return min_chars, max_chars, estimated


class Repository:
    def __init__(self, db: Database):
        self.db = db

    def _execute(self, conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
        return conn.cursor().execute(sql.replace("?", self.db.placeholder()), params)

    def _fetchone(self, conn: Any, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        cur = conn.cursor()
        cur.execute(sql.replace("?", self.db.placeholder()), params)
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def _fetchall(self, conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cur = conn.cursor()
        cur.execute(sql.replace("?", self.db.placeholder()), params)
        return [dict(row) for row in cur.fetchall()]

    def _last_id(self, cur: Any) -> int:
        return int(cur.lastrowid)

    def ensure_default_resources(self) -> tuple[int, int]:
        with self.db.session() as conn:
            author_id = self._upsert_resource(conn, "author_profiles", DEFAULT_AUTHOR)
            editor_id = self._upsert_resource(conn, "editor_profiles", DEFAULT_EDITOR)
            return author_id, editor_id

    def _upsert_resource(self, conn: Any, table: str, data: dict[str, Any]) -> int:
        found = self._fetchone(conn, f"SELECT id FROM {table} WHERE name = ?", (data["name"],))
        if found:
            return int(found["id"])
        fields = list(data.keys())
        ph = ",".join([self.db.placeholder()] * len(fields))
        cur = conn.cursor()
        cur.execute(f"INSERT INTO {table} ({','.join(fields)}) VALUES ({ph})", tuple(data.values()))
        return self._last_id(cur)

    def create_demo_book(self) -> int:
        raise ValueError("演示书和 sample 已取消，请直接创建正式作品。")

    def create_book(
        self,
        title: str,
        premise: str = "",
        genre: str = "",
        market_channel: str = "中国网文男频爽文",
        target_reader: str = "",
        pov_policy: str = "third_limited",
        target_chars_min: Any = 2200,
        target_chars_max: Any = 3200,
        story_mainline: str = "",
        worldbuilding: str = "",
        imported_outline: str = "",
        characters_text: str = "",
        estimated_total_words: Any = 1000000,
        book_outline: str = "",
    ) -> int:
        title = title.strip() or "未命名作品"
        if self.get_book_by_title(title, statuses=("active",)):
            raise ValueError("同名正式作品已存在，请改名或先归档旧作品。")
        premise = premise.strip() or "请补充作品核心卖点。"
        target_chars_min, target_chars_max, estimated_total_words = normalize_word_targets(target_chars_min, target_chars_max, estimated_total_words)
        outline = (book_outline or imported_outline or story_mainline or premise).strip()
        with self.db.session() as conn:
            author_id = self._upsert_resource(conn, "author_profiles", DEFAULT_AUTHOR)
            editor_id = self._upsert_resource(conn, "editor_profiles", DEFAULT_EDITOR)
            book_author_id = self._clone_author_for_book(conn, 0, author_id)
            book_editor_id = self._clone_editor_for_book(conn, 0, editor_id)
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(
                f"""INSERT INTO books
                (title, premise, status, genre, market_channel, target_reader, pov_policy, target_chars_min, target_chars_max,
                 story_mainline, worldbuilding, imported_outline, book_outline, estimated_total_words,
                 author_profile_id, editor_profile_id, book_author_profile_id, book_editor_profile_id)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (
                    title,
                    premise,
                    "active",
                    genre.strip(),
                    market_channel.strip(),
                    target_reader.strip(),
                    pov_policy.strip() or "third_limited",
                    target_chars_min,
                    target_chars_max,
                    story_mainline.strip(),
                    worldbuilding.strip(),
                    imported_outline.strip(),
                    outline,
                    estimated_total_words,
                    author_id,
                    editor_id,
                    book_author_id,
                    book_editor_id,
                ),
            )
            book_id = self._last_id(cur)
            self._execute(conn, "UPDATE book_author_profiles SET book_id = ? WHERE id = ?", (book_id, book_author_id))
            self._execute(conn, "UPDATE book_editor_profiles SET book_id = ? WHERE id = ?", (book_id, book_editor_id))
            self._seed_architecture(conn, book_id)
            self._seed_opening_material(conn, book_id, characters_text)
            self.log_event(conn, book_id, None, "book_created", "正式作品已创建；已生成卷纲和单元纲，未预置固定三章。")
            return book_id

    def _seed_architecture(self, conn: Any, book_id: int) -> None:
        book = self._fetchone(conn, "SELECT * FROM books WHERE id = ?", (book_id,))
        if not book:
            return
        self._seed_volumes_and_units(conn, book)
        self._insert_default_controls(conn, book_id)

    def _seed_volumes_and_units(self, conn: Any, book: dict[str, Any]) -> None:
        book_id = int(book["id"])
        if self._fetchone(conn, "SELECT id FROM volumes WHERE book_id = ? LIMIT 1", (book_id,)):
            return
        total_words = safe_int_field(book.get("estimated_total_words"), 1000000, 100000, 50000000, "estimated_total_words")
        target_min = safe_int_field(book.get("target_chars_min"), 2200, 1, 30000, "target_chars_min")
        target_max = safe_int_field(book.get("target_chars_max"), 3200, target_min, 50000, "target_chars_max")
        avg_chapter_words = max(1200, int((target_min + target_max) / 2))
        total_chapters = max(20, math.ceil(total_words / avg_chapter_words))
        volume_count = max(1, math.ceil(total_words / 200000))
        base_volume_chapters = max(20, math.ceil(total_chapters / volume_count))
        outline = book.get("book_outline") or book.get("imported_outline") or book.get("story_mainline") or book.get("premise") or "主角在压力中成长并取得阶段胜利。"
        ph = self.db.placeholder()
        cur = conn.cursor()
        start = 1
        for index in range(1, volume_count + 1):
            remaining = total_chapters - start + 1
            chapter_span = remaining if index == volume_count else min(base_volume_chapters, remaining)
            end = start + chapter_span - 1
            estimated_words = chapter_span * avg_chapter_words
            volume_title = f"第{index}卷：阶段推进"
            volume_goal = f"围绕全书大纲推进第{index}阶段胜负：{outline[:220]}"
            cur.execute(
                f"""INSERT INTO volumes
                (book_id, title, goal, estimated_words, core_conflict, stage_payoff, character_progression, foreshadowing_plan, start_chapter, end_chapter)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (
                    book_id,
                    volume_title,
                    volume_goal,
                    estimated_words,
                    "主角目标与阶段对手、规则、资源限制之间的正面冲突。",
                    "阶段性胜利必须付出代价，并打开下一卷问题。",
                    "主角能力、关系和选择压力逐步升级。",
                    "每卷设置、推进并部分回收关键伏笔，未批准伏笔不进入正文。",
                    start,
                    end,
                ),
            )
            volume_id = self._last_id(cur)
            self._seed_units_for_volume(conn, book, volume_id, start, end, avg_chapter_words, index)
            start = end + 1

    def _seed_units_for_volume(self, conn: Any, book: dict[str, Any], volume_id: int, start: int, end: int, avg_chapter_words: int, volume_index: int) -> None:
        ph = self.db.placeholder()
        cur = conn.cursor()
        unit_start = start
        unit_index = 1
        while unit_start <= end:
            recommended = 5 if end - unit_start + 1 >= 5 else end - unit_start + 1
            recommended = max(1, min(20, recommended))
            unit_end = min(end, unit_start + recommended - 1)
            cur.execute(
                f"""INSERT INTO story_arcs
                (book_id, volume_id, title, goal, pressure, cause, process, result, payoff, character_change, foreshadowing_progress,
                 recommended_chapters, start_chapter, end_chapter)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (
                    int(book["id"]),
                    volume_id,
                    f"第{volume_index}卷·单元{unit_index}",
                    "完成一次明确的起因、行动推进、阶段兑现，并服务当前卷目标。",
                    "资源、名望、规则、对手和时间压力轮换施压。",
                    "由上一单元结果或当前卷核心矛盾引发新压力。",
                    "主角通过判断、行动、交易或反击推进局势。",
                    "兑现一个小阶段结果，同时留下新代价或钩子。",
                    "至少有一次可感知爽点，但不机械重复打脸。",
                    "人物关系或主角判断发生可追踪变化。",
                    "推进或设置伏笔，不提前回收卷级/全书级伏笔。",
                    recommended,
                    unit_start,
                    unit_end,
                ),
            )
            unit_start = unit_end + 1
            unit_index += 1

    def _seed_opening_material(self, conn: Any, book_id: int, characters_text: str) -> None:
        ph = self.db.placeholder()
        cur = conn.cursor()
        if characters_text.strip():
            for raw in characters_text.splitlines():
                name = raw.strip().split("：", 1)[0].split(":", 1)[0].strip()
                if name:
                    cur.execute(
                        f"INSERT INTO characters (book_id, name, role_type, desire, fear, voice, biography) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
                        (book_id, name[:80], "main", "围绕主线追求阶段胜利", "失去关键筹码", "按作者设定调整", raw.strip()),
                    )
        else:
            cur.execute(
                f"INSERT INTO characters (book_id, name, role_type, desire, fear, voice, biography) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
                (book_id, "主角", "protagonist", "在规则压迫中夺回主动权", "胜利代价反噬自身或同伴", "冷静、有判断，不喊口号", "开书时由系统生成，待作者补充小传。"),
            )
        cur.execute(
            f"INSERT INTO canon_facts (book_id, fact_type, content, status) VALUES ({ph},{ph},{ph},{ph})",
            (book_id, "canon_ledger", "硬设定、人物硬事实、关系硬状态和伏笔账本不可有损压缩，只能人工批准后进入。", "official"),
        )

    def _insert_default_controls(self, conn: Any, book_id: int) -> None:
        book = self._fetchone(conn, "SELECT * FROM books WHERE id = ?", (book_id,))
        ph = self.db.placeholder()
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO style_profiles (book_id, name, rules, locked) VALUES ({ph},{ph},{ph},{ph})",
            (book_id, "男频爽文-自然节奏", "首屏有压力；主角用行动和判断推进；设定只通过冲突、代价、证据、对白露出。", 1),
        )
        cur.execute(
            f"""INSERT INTO production_settings
            (book_id, market_channel, target_chars_min, target_chars_max, chapter_unit_size, pov_policy, hook_policy, pacing_policy)
            VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
            (
                book_id,
                (book or {}).get("market_channel") or "中国网文男频爽文",
                safe_int_field((book or {}).get("target_chars_min"), 2200, 1, 30000, "target_chars_min"),
                safe_int_field((book or {}).get("target_chars_max"), 3200, 1, 50000, "target_chars_max"),
                5,
                (book or {}).get("pov_policy") or "third_limited",
                "每章至少有一个可感知压力源和一个可兑现的小爽点；反转、打脸、奖励、惩罚轮换使用。",
                "章节服务单元，单元服务卷；不越级推进，不用说明书替代剧情。",
            ),
        )

    def _clone_author_for_book(self, conn: Any, book_id: int, profile_id: int) -> int:
        profile = self._fetchone(conn, "SELECT * FROM author_profiles WHERE id = ?", (profile_id,)) or DEFAULT_AUTHOR
        ph = self.db.placeholder()
        cur = conn.cursor()
        cur.execute(
            f"""INSERT INTO book_author_profiles
            (book_id, source_profile_id, name, genre, pov_preference, sentence_rhythm, dialogue_style, payoff_preference, forbidden_items, prompt_rules, sample_summary)
            VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
            (book_id, profile_id, profile["name"], profile["genre"], profile["pov_preference"], profile["sentence_rhythm"], profile["dialogue_style"], profile["payoff_preference"], profile["forbidden_items"], profile["prompt_rules"], ""),
        )
        return self._last_id(cur)

    def _clone_editor_for_book(self, conn: Any, book_id: int, profile_id: int) -> int:
        profile = self._fetchone(conn, "SELECT * FROM editor_profiles WHERE id = ?", (profile_id,)) or DEFAULT_EDITOR
        ph = self.db.placeholder()
        cur = conn.cursor()
        cur.execute(
            f"""INSERT INTO book_editor_profiles
            (book_id, source_profile_id, name, platform, word_count_rule, pov_rule, structure_rule, payoff_rule, pollution_rule, reject_threshold)
            VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
            (book_id, profile_id, profile["name"], profile["platform"], profile["word_count_rule"], profile["pov_rule"], profile["structure_rule"], profile["payoff_rule"], profile["pollution_rule"], int(profile["reject_threshold"])),
        )
        return self._last_id(cur)

    def list_books(self, status: str | None = "active") -> list[Book]:
        with self.db.session() as conn:
            if status is None:
                rows = self._fetchall(conn, "SELECT id, title, premise, status FROM books WHERE status != ? ORDER BY id", ("sample",))
            else:
                rows = self._fetchall(conn, "SELECT id, title, premise, status FROM books WHERE status = ? ORDER BY id", (status,))
        return [Book(**row) for row in rows]

    def get_book_by_title(self, title: str, statuses: tuple[str, ...] = ("active",)) -> Book | None:
        placeholders = ",".join(["?"] * len(statuses))
        with self.db.session() as conn:
            row = self._fetchone(conn, f"SELECT id, title, premise, status FROM books WHERE title = ? AND status IN ({placeholders})", (title, *statuses))
        return Book(**row) if row else None

    def get_book(self, book_id: int) -> Book | None:
        with self.db.session() as conn:
            row = self._fetchone(conn, "SELECT id, title, premise, status FROM books WHERE id = ?", (book_id,))
        return Book(**row) if row else None

    def get_book_record(self, book_id: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT * FROM books WHERE id = ?", (book_id,))

    def update_book_setup(self, book_id: int, data: dict[str, Any], force_outline: bool = False) -> None:
        current = self.get_book_record(book_id) or {}
        outline_locked = bool(int(current.get("outline_locked") or 0))
        allowed = ["title", "premise", "genre", "market_channel", "target_reader", "pov_policy", "target_chars_min", "target_chars_max", "story_mainline", "worldbuilding", "estimated_total_words"]
        if not outline_locked or force_outline:
            allowed.extend(["imported_outline", "book_outline"])
        values = {key: data.get(key, current.get(key, "")) for key in allowed}
        values["target_chars_min"], values["target_chars_max"], values["estimated_total_words"] = normalize_word_targets(
            values.get("target_chars_min"),
            values.get("target_chars_max"),
            values.get("estimated_total_words"),
        )
        with self.db.session() as conn:
            assigns = ", ".join([f"{key} = ?" for key in allowed])
            self._execute(conn, f"UPDATE books SET {assigns} WHERE id = ?", (*values.values(), book_id))
            self.log_event(conn, book_id, None, "book_setup_updated", "开书设定已更新")
        controls = self.get_book_controls(book_id)
        self.update_style_and_settings(
            book_id,
            controls["style"]["rules"] if controls.get("style") else "",
            values.get("market_channel", current.get("market_channel", "")),
            values["target_chars_min"],
            values["target_chars_max"],
            5,
            values.get("pov_policy", current.get("pov_policy", "third_limited")),
            (controls.get("settings") or {}).get("hook_policy", "每章至少有一个压力源和一个小兑现。"),
            (controls.get("settings") or {}).get("pacing_policy", "章节服务单元，单元服务卷，不越级推进。"),
        )

    def update_book(self, book_id: int, title: str, premise: str) -> None:
        self.update_book_setup(book_id, {"title": title, "premise": premise, **(self.get_book_record(book_id) or {})})

    def lock_book_outline(self, book_id: int) -> None:
        with self.db.session() as conn:
            self._execute(conn, "UPDATE books SET outline_locked = ?, outline_confirmed_at = ? WHERE id = ?", (1, datetime.now(timezone.utc).isoformat(timespec="seconds"), book_id))
            self.log_event(conn, book_id, None, "book_outline_locked", "全书结构化大纲已确认锁定")

    def unlock_book_outline(self, book_id: int) -> None:
        with self.db.session() as conn:
            self._execute(conn, "UPDATE books SET outline_locked = ?, outline_confirmed_at = NULL WHERE id = ?", (0, book_id))
            self.log_event(conn, book_id, None, "book_outline_unlocked", "全书结构化大纲已解锁修订")

    def archive_book(self, book_id: int) -> None:
        with self.db.session() as conn:
            self._execute(conn, "UPDATE books SET status = ? WHERE id = ?", ("archived", book_id))
            self.log_event(conn, book_id, None, "book_archived", "作品已归档")

    def restore_book(self, book_id: int) -> None:
        book = self.get_book(book_id)
        if book and self.get_book_by_title(book.title, statuses=("active",)):
            raise ValueError("恢复失败：正式书库已有同名作品。")
        with self.db.session() as conn:
            self._execute(conn, "UPDATE books SET status = ? WHERE id = ?", ("active", book_id))
            self.log_event(conn, book_id, None, "book_restored", "作品已恢复")

    def delete_book_permanently(self, book_id: int) -> None:
        tables = [
            "volumes", "story_arcs", "chapter_batches", "chapter_candidates", "chapter_plans", "chapter_tasks",
            "chapter_state_snapshots", "chapter_transitions", "editorial_decisions",
            "model_call_logs", "production_runs", "workflow_runs", "workflow_events", "construction_packets", "chapter_drafts",
            "rework_tickets", "human_approval_logs", "official_canon", "canonized_events",
            "ledger_update_candidates", "character_states", "relationship_states",
            "foreshadowing_ledger", "setting_ledger", "progression_ledger",
            "style_profiles", "production_settings", "book_author_profiles", "book_editor_profiles",
            "characters", "relationships", "foreshadowings", "canon_facts", "visibility_rules",
            "artifacts", "chapter_bodies", "pipeline_runs", "rewrite_tasks", "continuity_memories",
            "continuity_atoms", "memory_retrieval_logs", "drift_reports", "export_records", "events",
            "export_versions",
        ]
        with self.db.session() as conn:
            for table in tables:
                self._execute(conn, f"DELETE FROM {table} WHERE book_id = ?", (book_id,))
            self._execute(conn, "DELETE FROM books WHERE id = ?", (book_id,))

    def rebuild_generated_planning_for_all_books(self) -> dict[str, int]:
        totals = {"books": 0, "backups": 0, "deleted_artifacts": 0, "deleted_plans": 0, "deleted_batches": 0}
        with self.db.session() as conn:
            books = self._fetchall(conn, "SELECT id FROM books WHERE status = ?", ("active",))
            totals["books"] = len(books)
            for book in books:
                book_id = int(book["id"])
                confirmed_sql = "SELECT chapter_no FROM chapter_bodies WHERE book_id = ? AND status IN ('human_confirmed','exported')"
                old = {
                    "volumes": self._fetchall(conn, "SELECT * FROM volumes WHERE book_id = ? AND manual_edited = 0", (book_id,)),
                    "arcs": self._fetchall(conn, "SELECT * FROM story_arcs WHERE book_id = ? AND manual_edited = 0", (book_id,)),
                    "plans": self._fetchall(conn, f"SELECT * FROM chapter_plans WHERE book_id = ? AND chapter_no NOT IN ({confirmed_sql})", (book_id, book_id)),
                }
                if old["volumes"] or old["arcs"] or old["plans"]:
                    ph = self.db.placeholder()
                    conn.cursor().execute(
                        f"INSERT INTO artifacts (book_id, chapter_no, artifact_type, status, content, visibility) VALUES ({ph},{ph},{ph},{ph},{ph},{ph})",
                        (book_id, None, "planning_backup", "archived", json.dumps(json_safe(old), ensure_ascii=False, indent=2), "internal"),
                    )
                    totals["backups"] += 1
                for artifact_type in ["author_brief", "ref_pack", "draft", "review", "generation_error"]:
                    cur = self._execute(conn, f"DELETE FROM artifacts WHERE book_id = ? AND artifact_type = ? AND chapter_no NOT IN ({confirmed_sql})", (book_id, artifact_type, book_id))
                    totals["deleted_artifacts"] += max(0, int(cur.rowcount or 0))
                self._execute(conn, f"DELETE FROM pipeline_runs WHERE book_id = ? AND chapter_no NOT IN ({confirmed_sql})", (book_id, book_id))
                self._execute(conn, f"DELETE FROM rewrite_tasks WHERE book_id = ? AND chapter_no NOT IN ({confirmed_sql})", (book_id, book_id))
                cur = self._execute(conn, f"DELETE FROM chapter_plans WHERE book_id = ? AND chapter_no NOT IN ({confirmed_sql})", (book_id, book_id))
                totals["deleted_plans"] += max(0, int(cur.rowcount or 0))
                cur = self._execute(conn, "DELETE FROM chapter_batches WHERE book_id = ?", (book_id,))
                totals["deleted_batches"] += max(0, int(cur.rowcount or 0))
                self._execute(conn, "DELETE FROM story_arcs WHERE book_id = ? AND manual_edited = 0", (book_id,))
                self._execute(conn, "DELETE FROM volumes WHERE book_id = ? AND manual_edited = 0", (book_id,))
                record = self._fetchone(conn, "SELECT * FROM books WHERE id = ?", (book_id,))
                if record:
                    self._seed_volumes_and_units(conn, record)
                self.log_event(conn, book_id, None, "planning_rebuilt", "已清理旧模板规划和未导出中间产物，保留已确认/已导出正文。")
        return totals

    def update_cover(self, book_id: int, cover_path: str) -> None:
        with self.db.session() as conn:
            self._execute(conn, "UPDATE books SET cover_path = ? WHERE id = ?", (cover_path, book_id))
            self.log_event(conn, book_id, None, "cover_updated", "封面已更新")

    def list_volumes(self, book_id: int) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            return self._fetchall(conn, "SELECT * FROM volumes WHERE book_id = ? ORDER BY start_chapter, id", (book_id,))

    def list_arcs(self, book_id: int, volume_id: int | None = None) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            if volume_id:
                return self._fetchall(conn, "SELECT * FROM story_arcs WHERE book_id = ? AND volume_id = ? ORDER BY start_chapter, id", (book_id, volume_id))
            return self._fetchall(conn, "SELECT * FROM story_arcs WHERE book_id = ? ORDER BY start_chapter, id", (book_id,))

    def get_volume(self, volume_id: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT * FROM volumes WHERE id = ?", (volume_id,))

    def get_arc(self, arc_id: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT * FROM story_arcs WHERE id = ?", (arc_id,))

    def get_current_unit(self, book_id: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            last = self._fetchone(conn, "SELECT MAX(chapter_no) AS chapter_no FROM chapter_plans WHERE book_id = ?", (book_id,))
            next_no = int((last or {}).get("chapter_no") or 0) + 1
            arc = self._fetchone(conn, "SELECT * FROM story_arcs WHERE book_id = ? AND start_chapter <= ? AND end_chapter >= ? ORDER BY start_chapter LIMIT 1", (book_id, next_no, next_no))
            if not arc:
                arc = self._fetchone(conn, "SELECT * FROM story_arcs WHERE book_id = ? ORDER BY start_chapter LIMIT 1", (book_id,))
            return arc

    def get_book_controls(self, book_id: int) -> dict[str, Any]:
        with self.db.session() as conn:
            book = self._fetchone(conn, "SELECT * FROM books WHERE id = ?", (book_id,))
            volume = self._fetchone(conn, "SELECT * FROM volumes WHERE book_id = ? ORDER BY start_chapter LIMIT 1", (book_id,))
            arc = self._fetchone(conn, "SELECT * FROM story_arcs WHERE book_id = ? ORDER BY start_chapter LIMIT 1", (book_id,))
            style = self._fetchone(conn, "SELECT * FROM style_profiles WHERE book_id = ? AND locked = 1 ORDER BY id LIMIT 1", (book_id,))
            settings = self._fetchone(conn, "SELECT * FROM production_settings WHERE book_id = ?", (book_id,))
            author = self._fetchone(conn, "SELECT * FROM book_author_profiles WHERE id = ?", (book.get("book_author_profile_id") if book else None,))
            editor = self._fetchone(conn, "SELECT * FROM book_editor_profiles WHERE id = ?", (book.get("book_editor_profile_id") if book else None,))
        return {"book": book, "volume": volume, "arc": arc, "style": style, "settings": settings or {}, "author_profile": author, "editor_profile": editor, "pov_label": POV_LABELS.get((book or {}).get("pov_policy", "third_limited"), "第三人称有限视角")}

    def get_production_settings(self, book_id: int) -> dict[str, Any]:
        return self.get_book_controls(book_id)["settings"]

    def update_style_and_settings(self, book_id: int, style_rules: str, market_channel: str, target_chars_min: Any, target_chars_max: Any, chapter_unit_size: Any, pov_policy: str, hook_policy: str, pacing_policy: str) -> None:
        target_chars_min = safe_int_field(target_chars_min, 2200, 1, 30000, "target_chars_min")
        target_chars_max = safe_int_field(target_chars_max, 3200, target_chars_min, 50000, "target_chars_max")
        chapter_unit_size = safe_int_field(chapter_unit_size, 5, 1, 20, "chapter_unit_size")
        with self.db.session() as conn:
            self._execute(conn, "UPDATE style_profiles SET rules = ? WHERE book_id = ? AND locked = 1", (style_rules.strip(), book_id))
            ph = self.db.placeholder()
            if self.db.is_mysql:
                sql = f"""INSERT INTO production_settings (book_id, market_channel, target_chars_min, target_chars_max, chapter_unit_size, pov_policy, hook_policy, pacing_policy)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
                    ON DUPLICATE KEY UPDATE market_channel=VALUES(market_channel), target_chars_min=VALUES(target_chars_min), target_chars_max=VALUES(target_chars_max), chapter_unit_size=VALUES(chapter_unit_size), pov_policy=VALUES(pov_policy), hook_policy=VALUES(hook_policy), pacing_policy=VALUES(pacing_policy)"""
            else:
                sql = f"""INSERT INTO production_settings (book_id, market_channel, target_chars_min, target_chars_max, chapter_unit_size, pov_policy, hook_policy, pacing_policy)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
                    ON CONFLICT(book_id) DO UPDATE SET market_channel=excluded.market_channel, target_chars_min=excluded.target_chars_min, target_chars_max=excluded.target_chars_max, chapter_unit_size=excluded.chapter_unit_size, pov_policy=excluded.pov_policy, hook_policy=excluded.hook_policy, pacing_policy=excluded.pacing_policy"""
            conn.cursor().execute(sql, (book_id, market_channel.strip(), target_chars_min, target_chars_max, chapter_unit_size, pov_policy.strip(), hook_policy.strip(), pacing_policy.strip()))

    def update_architecture(self, book_id: int, volume_title: str, volume_goal: str, arc_title: str, arc_goal: str, arc_pressure: str) -> None:
        with self.db.session() as conn:
            volume = self._fetchone(conn, "SELECT * FROM volumes WHERE book_id = ? ORDER BY start_chapter LIMIT 1", (book_id,))
            arc = self._fetchone(conn, "SELECT * FROM story_arcs WHERE book_id = ? ORDER BY start_chapter LIMIT 1", (book_id,))
            if volume:
                self._execute(conn, "UPDATE volumes SET title = ?, goal = ?, manual_edited = 1 WHERE id = ?", (volume_title.strip(), volume_goal.strip(), volume["id"]))
            if arc:
                self._execute(conn, "UPDATE story_arcs SET title = ?, goal = ?, pressure = ?, manual_edited = 1 WHERE id = ?", (arc_title.strip(), arc_goal.strip(), arc_pressure.strip(), arc["id"]))
            self.log_event(conn, book_id, None, "architecture_updated", "卷纲/单元纲已更新")

    def update_volume(self, book_id: int, volume_id: int, data: dict[str, Any]) -> None:
        fields = ["title", "goal", "estimated_words", "core_conflict", "stage_payoff", "character_progression", "foreshadowing_plan", "start_chapter", "end_chapter"]
        values = [data.get(field, "") for field in fields]
        values[2] = safe_int_field(values[2], 200000, 1000, 50000000, "estimated_words")
        values[7] = safe_int_field(values[7], 1, 1, 100000, "start_chapter")
        values[8] = safe_int_field(values[8], values[7], values[7], 100000, "end_chapter")
        with self.db.session() as conn:
            self._execute(conn, "UPDATE volumes SET title=?, goal=?, estimated_words=?, core_conflict=?, stage_payoff=?, character_progression=?, foreshadowing_plan=?, start_chapter=?, end_chapter=?, manual_edited=1 WHERE book_id=? AND id=?", (*values, book_id, volume_id))
            self.log_event(conn, book_id, None, "volume_updated", "卷纲已保存")

    def update_arc(self, book_id: int, arc_id: int, data: dict[str, Any]) -> None:
        fields = ["title", "goal", "pressure", "cause", "process", "result", "payoff", "character_change", "foreshadowing_progress", "recommended_chapters", "start_chapter", "end_chapter", "status"]
        values = [data.get(field, "") for field in fields]
        values[9] = safe_int_field(values[9], 5, 1, 20, "recommended_chapters")
        values[10] = safe_int_field(values[10], 1, 1, 100000, "start_chapter")
        values[11] = safe_int_field(values[11], values[10], values[10], 100000, "end_chapter")
        values[12] = values[12] or "planned"
        with self.db.session() as conn:
            self._execute(conn, "UPDATE story_arcs SET title=?, goal=?, pressure=?, cause=?, process=?, result=?, payoff=?, character_change=?, foreshadowing_progress=?, recommended_chapters=?, start_chapter=?, end_chapter=?, status=?, manual_edited=1 WHERE book_id=? AND id=?", (*values, book_id, arc_id))
            self.log_event(conn, book_id, None, "unit_updated", "单元纲已保存")

    def list_chapter_plans(self, book_id: int) -> list[ChapterPlan]:
        with self.db.session() as conn:
            rows = self._fetchall(conn, "SELECT * FROM chapter_plans WHERE book_id = ? ORDER BY chapter_no", (book_id,))
        return [ChapterPlan(**{key: row[key] for key in ChapterPlan.__dataclass_fields__ if key in row}) for row in rows]

    def list_chapter_plan_rows(self, book_id: int, batch_id: int | None = None) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            if batch_id:
                return self._fetchall(conn, "SELECT cp.*, v.title AS volume_title, a.title AS arc_title FROM chapter_plans cp LEFT JOIN volumes v ON v.id=cp.volume_id LEFT JOIN story_arcs a ON a.id=cp.arc_id WHERE cp.book_id = ? AND cp.batch_id = ? ORDER BY cp.chapter_no", (book_id, batch_id))
            return self._fetchall(conn, "SELECT cp.*, v.title AS volume_title, a.title AS arc_title FROM chapter_plans cp LEFT JOIN volumes v ON v.id=cp.volume_id LEFT JOIN story_arcs a ON a.id=cp.arc_id WHERE cp.book_id = ? ORDER BY cp.chapter_no", (book_id,))

    def get_chapter_plan(self, book_id: int, chapter_no: int) -> ChapterPlan | None:
        with self.db.session() as conn:
            row = self._fetchone(conn, "SELECT * FROM chapter_plans WHERE book_id = ? AND chapter_no = ?", (book_id, chapter_no))
        return ChapterPlan(**{key: row[key] for key in ChapterPlan.__dataclass_fields__ if key in row}) if row else None

    def get_chapter_plan_row(self, book_id: int, chapter_no: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT cp.*, v.title AS volume_title, a.title AS arc_title FROM chapter_plans cp LEFT JOIN volumes v ON v.id=cp.volume_id LEFT JOIN story_arcs a ON a.id=cp.arc_id WHERE cp.book_id = ? AND cp.chapter_no = ?", (book_id, chapter_no))

    def update_chapter_plan(self, book_id: int, chapter_no: int, title: str, objective: str, allowed_reveals: str, forbidden_reveals: str, pace_limit: str, plot_summary: str = "", target_chars: Any = 2600, unique_task: str = "", core_event: str = "", tech_progression: str = "", character_roles: str = "", antagonist_move: str = "", external_pressure: str = "", irreversible_change: str = "", ending_hook: str = "", no_repeat_guard: str = "") -> None:
        with self.db.session() as conn:
            current = self._fetchone(conn, "SELECT * FROM chapter_plans WHERE book_id = ? AND chapter_no = ?", (book_id, chapter_no)) or {}
            values = (
                title.strip(),
                objective.strip(),
                allowed_reveals.strip(),
                forbidden_reveals.strip(),
                pace_limit.strip(),
                plot_summary.strip(),
                safe_int_field(target_chars, int(current.get("target_chars") or 2600), 1, 30000, "target_chars"),
                (unique_task or current.get("unique_task") or "").strip(),
                (core_event or current.get("core_event") or "").strip(),
                (tech_progression or current.get("tech_progression") or "").strip(),
                (character_roles or current.get("character_roles") or "").strip(),
                (antagonist_move or current.get("antagonist_move") or "").strip(),
                (external_pressure or current.get("external_pressure") or "").strip(),
                (irreversible_change or current.get("irreversible_change") or "").strip(),
                (ending_hook or current.get("ending_hook") or "").strip(),
                (no_repeat_guard or current.get("no_repeat_guard") or "").strip(),
                book_id,
                chapter_no,
            )
            self._execute(conn, """UPDATE chapter_plans SET title = ?, objective = ?, allowed_reveals = ?, forbidden_reveals = ?, pace_limit = ?, plot_summary = ?, target_chars = ?, unique_task = ?, core_event = ?, tech_progression = ?, character_roles = ?, antagonist_move = ?, external_pressure = ?, irreversible_change = ?, ending_hook = ?, no_repeat_guard = ?, manual_edited = 1 WHERE book_id = ? AND chapter_no = ?""", values)
            self.log_event(conn, book_id, chapter_no, "chapter_plan_updated", "章节卡片已保存")

    def _chapter_numbers_for_batch(self, conn: Any, book_id: int, count: int, volume_id: int | None = None, arc_id: int | None = None) -> list[int]:
        params: list[Any] = [book_id]
        plan_scope = ""
        scope_start = 1
        scope_end = None
        if volume_id:
            plan_scope += " AND volume_id = ?"
            params.append(volume_id)
            volume = self._fetchone(conn, "SELECT start_chapter, end_chapter FROM volumes WHERE book_id = ? AND id = ?", (book_id, volume_id))
            if volume:
                scope_start = int(volume.get("start_chapter") or 1)
                scope_end = int(volume.get("end_chapter") or 0) or None
        if arc_id:
            plan_scope += " AND arc_id = ?"
            params.append(arc_id)
            arc = self._fetchone(conn, "SELECT start_chapter, end_chapter FROM story_arcs WHERE book_id = ? AND id = ?", (book_id, arc_id))
            if arc:
                scope_start = int(arc.get("start_chapter") or scope_start)
                scope_end = int(arc.get("end_chapter") or 0) or scope_end
        plans = self._fetchall(conn, f"SELECT chapter_no FROM chapter_plans WHERE book_id = ?{plan_scope} ORDER BY chapter_no", tuple(params))
        plan_nos = {int(row["chapter_no"]) for row in plans}
        bodies = self._fetchall(conn, "SELECT chapter_no FROM chapter_bodies WHERE book_id = ? ORDER BY chapter_no", (book_id,))
        body_nos = {int(row["chapter_no"]) for row in bodies}
        numbers: list[int] = []
        upper = max(plan_nos | body_nos | {0})
        range_end = max(upper, scope_end or upper)
        for no in range(scope_start, range_end + 1):
            if no in body_nos:
                continue
            numbers.append(no)
            if len(numbers) >= count:
                return numbers
        next_no = max(upper + 1, (scope_end or 0) + 1)
        while len(numbers) < count:
            numbers.append(next_no)
            next_no += 1
        return numbers

    def find_reusable_chapter_slots(self, book_id: int, count: int, volume_id: int | None = None, arc_id: int | None = None) -> list[int]:
        with self.db.session() as conn:
            return self._chapter_numbers_for_batch(conn, book_id, safe_int_field(count, 1, 1, 20, "chapter_count"), volume_id, arc_id)

    def create_or_reuse_chapter_batch(self, book_id: int, chapter_count: int | None = None, volume_id: int | None = None, arc_id: int | None = None) -> int:
        with self.db.session() as conn:
            if arc_id:
                arc = self._fetchone(conn, "SELECT * FROM story_arcs WHERE book_id = ? AND id = ?", (book_id, arc_id))
            else:
                missing = self._chapter_numbers_for_batch(conn, book_id, 1, volume_id, None)
                next_no = missing[0] if missing else 1
                arc = self._fetchone(conn, "SELECT * FROM story_arcs WHERE book_id = ? AND start_chapter <= ? AND end_chapter >= ? ORDER BY start_chapter LIMIT 1", (book_id, next_no, next_no))
                if not arc:
                    arc = self._fetchone(conn, "SELECT * FROM story_arcs WHERE book_id = ? ORDER BY start_chapter LIMIT 1", (book_id,))
            if not arc:
                book = self._fetchone(conn, "SELECT * FROM books WHERE id = ?", (book_id,))
                self._seed_volumes_and_units(conn, book)
                arc = self._fetchone(conn, "SELECT * FROM story_arcs WHERE book_id = ? ORDER BY start_chapter LIMIT 1", (book_id,))
            if not arc:
                raise ValueError("缺少单元纲，无法生成章节批次。")
            volume = self._fetchone(conn, "SELECT * FROM volumes WHERE id = ?", (volume_id or arc["volume_id"],))
            recommended = max(1, min(20, int(arc.get("recommended_chapters") or 5)))
            count = safe_int_field(chapter_count, recommended, 1, 20, "chapter_count")
            numbers = self._chapter_numbers_for_batch(conn, book_id, count, int(volume["id"]) if volume else None, int(arc["id"]))
            start = min(numbers)
            end = max(numbers)
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(
                f"""INSERT INTO chapter_batches
                (book_id, volume_id, arc_id, start_chapter, end_chapter, chapter_count, recommended_count, author_count, status, progress_message)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (book_id, volume["id"], arc["id"], start, end, count, recommended, count, "planning", "章节卡片已根据当前单元纲生成，等待作者确认。"),
            )
            batch_id = self._last_id(cur)
            target_chars = int(((self._fetchone(conn, "SELECT * FROM production_settings WHERE book_id = ?", (book_id,)) or {}).get("target_chars_max") or 2600))
            for no in numbers:
                existing = self._fetchone(conn, "SELECT * FROM chapter_plans WHERE book_id = ? AND chapter_no = ?", (book_id, no))
                if existing:
                    self._execute(conn, "UPDATE chapter_plans SET batch_id = ?, volume_id = ?, arc_id = ? WHERE book_id = ? AND chapter_no = ?", (batch_id, volume["id"], arc["id"], book_id, no))
                else:
                    cur.execute(
                        f"""INSERT INTO chapter_plans
                        (book_id, volume_id, arc_id, batch_id, chapter_no, title, objective, allowed_reveals, forbidden_reveals, pace_limit, plot_summary, target_chars, unique_task, core_event, tech_progression, character_roles, antagonist_move, external_pressure, irreversible_change, ending_hook, no_repeat_guard)
                        VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                        (
                            book_id,
                            volume["id"],
                            arc["id"],
                            batch_id,
                            no,
                            f"第{no}章 待规划",
                            "待规划 Agent 生成本章细纲。",
                            "待规划。",
                            "待规划。",
                            "待规划。",
                            "",
                            target_chars,
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                        ),
                    )
            self._execute(conn, "UPDATE books SET current_chapter_no = ? WHERE id = ?", (end, book_id))
            self.log_event(conn, book_id, None, "chapter_batch_created", f"已创建/复用第 {start}-{end} 章卡片")
            return batch_id

    def create_chapter_batch(self, book_id: int, chapter_count: int | None = None, volume_id: int | None = None, arc_id: int | None = None) -> int:
        return self.create_or_reuse_chapter_batch(book_id, chapter_count, volume_id, arc_id)

    def apply_planned_chapter_cards(self, book_id: int, batch_id: int, planned: list[dict[str, Any]]) -> None:
        if not planned:
            self.update_batch_status(batch_id, "planning_failed", "章节规划失败，请重试或手写细纲。", "规划 Agent 未返回可用章节细纲。")
            return
        by_no = {int(item["chapter_no"]): item for item in planned if int(item.get("chapter_no") or 0)}
        with self.db.session() as conn:
            rows = self._fetchall(conn, "SELECT * FROM chapter_plans WHERE book_id = ? AND batch_id = ? ORDER BY chapter_no", (book_id, batch_id))
            for row in rows:
                item = by_no.get(int(row["chapter_no"]))
                if not item:
                    continue
                target_chars = safe_int_field(item.get("target_chars") or row.get("target_chars") or 2600, row.get("target_chars") or 2600, 1, 30000, "target_chars")
                self._execute(
                    conn,
                    """UPDATE chapter_plans SET title=?, objective=?, allowed_reveals=?, forbidden_reveals=?, pace_limit=?, plot_summary=?, target_chars=?, unique_task=?, core_event=?, tech_progression=?, character_roles=?, antagonist_move=?, external_pressure=?, irreversible_change=?, ending_hook=?, no_repeat_guard=? WHERE book_id=? AND chapter_no=?""",
                    (
                        row["title"] if self._should_preserve_chapter_title(row) else item.get("title", row["title"]),
                        item.get("objective", ""),
                        item.get("allowed_reveals", ""),
                        item.get("forbidden_reveals", ""),
                        item.get("pace_limit", ""),
                        item.get("plot_summary", ""),
                        target_chars,
                        item.get("unique_task", ""),
                        item.get("core_event", ""),
                        item.get("tech_progression", ""),
                        item.get("character_roles", ""),
                        item.get("antagonist_move", ""),
                        item.get("external_pressure", ""),
                        item.get("irreversible_change", ""),
                        item.get("ending_hook", ""),
                        item.get("no_repeat_guard", ""),
                        book_id,
                        int(row["chapter_no"]),
                    ),
                )
            self._execute(conn, "UPDATE chapter_batches SET status = ?, progress_message = ?, error = ? WHERE id = ?", ("planning", "章节卡片已由规划 Agent 生成，等待作者确认。", "", batch_id))
            self.log_event(conn, book_id, None, "chapter_batch_planned", "章节批次已完成顺序细纲规划")

    def _should_preserve_chapter_title(self, row: dict[str, Any]) -> bool:
        return int(row.get("manual_edited") or 0) == 1

    def _fill_missing_chapter_structure(self, conn: Any, book_id: int, chapter_no: int, structure: dict[str, str]) -> None:
        current = self._fetchone(conn, "SELECT * FROM chapter_plans WHERE book_id = ? AND chapter_no = ?", (book_id, chapter_no)) or {}
        old_template = "承接单元起因，推进经过，并为结果兑现蓄力"
        updates: dict[str, str] = {}
        for field in ["unique_task", "core_event", "tech_progression", "character_roles", "antagonist_move", "external_pressure", "irreversible_change", "ending_hook", "no_repeat_guard"]:
            if not str(current.get(field) or "").strip():
                updates[field] = structure[field]
        if old_template in str(current.get("objective") or ""):
            updates["objective"] = structure["objective"]
        if not str(current.get("plot_summary") or "").strip() or "本章留下下一步钩子" in str(current.get("plot_summary") or ""):
            updates["plot_summary"] = structure["plot_summary"]
        if not updates:
            return
        set_clause = ", ".join(f"{field} = ?" for field in updates)
        values = list(updates.values()) + [book_id, chapter_no]
        self._execute(conn, f"UPDATE chapter_plans SET {set_clause} WHERE book_id = ? AND chapter_no = ?", values)

    def _build_chapter_structure(self, conn: Any, book_id: int, volume: dict[str, Any], arc: dict[str, Any], chapter_no: int, offset: int, count: int) -> dict[str, str]:
        previous = self._fetchone(conn, "SELECT title, core_event, tech_progression, irreversible_change, ending_hook FROM chapter_plans WHERE book_id = ? AND chapter_no < ? ORDER BY chapter_no DESC LIMIT 1", (book_id, chapter_no)) or {}
        characters = self._fetchall(conn, "SELECT name, role_type FROM characters WHERE book_id = ? ORDER BY id LIMIT 4", (book_id,))
        char_names = [row["name"] for row in characters if row.get("name")]
        lead = char_names[0] if char_names else "主角"
        support = "、".join(char_names[1:3]) if len(char_names) > 1 else "关键同伴"
        phase = [
            ("确认上一章后果", "把上一章结尾造成的损失、承诺或新线索落到具体行动上", "复盘上一章结果，排除一个错误方向，确定本章试验/行动入口"),
            ("提出修正方案", "用新判断改写原计划，并让支持角色承担验证、协调或牺牲职能", "根据异常线索提出修正方案，同时暴露新的限制条件"),
            ("遭遇升级阻力", "让外部压力或对手动作改变资源、时间或权限条件", "新方案在更高压力下试运行，出现不同于上一章的新故障"),
            ("完成阶段兑现", "让本单元目标产生可见结果，并留下下一阶段代价", "验证修正方向，得到新参数/新证据/新权限，同时付出代价"),
            ("转入下一问题", "把小胜利转化为更大的外部问题或组织升级", "把阶段成果交给团队消化，打开下一层技术难题"),
        ][(offset - 1) % 5]
        title = f"第{chapter_no}章 {phase[0]}"
        arc_goal = arc.get("goal") or "完成当前单元推进"
        cause = arc.get("cause") or arc.get("pressure") or "上一章结果带来新压力"
        process = arc.get("process") or "主角通过判断、行动和验证推进局势"
        result = arc.get("result") or "形成阶段结果并留下代价"
        payoff = arc.get("payoff") or "用具体行动兑现爽点"
        prev_hook = previous.get("ending_hook") or previous.get("irreversible_change") or "上一章留下的未解决钩子"
        core_event = f"{lead}围绕“{phase[0]}”处理{prev_hook}，把{cause}推进到一次具体行动。"
        unique_task = f"本章只完成一件事：{phase[1]}。不得重复上一章事件：{previous.get('core_event', '无')}。"
        tech_progression = f"{phase[2]}；技术/方案链条必须从“{process}”推进到“{result}”，不能再次证明同一个旧结论。"
        character_roles = f"{lead}负责判断和承担代价；{support}负责验证、协调、反证或提出边界；阻力人物必须改变压力方式。"
        antagonist_move = "阻力不重复上一章，必须从质疑数据、限制资源、改变期限、提出替代方案、引入外部压力中选择新的动作。"
        external_pressure = f"外部压力来自{volume.get('core_conflict') or arc.get('pressure') or '资源、期限、组织后果或更高层需求'}，必须具体落到本章行动。"
        irreversible_change = f"本章结束必须改变至少一项：权限、资源、技术认知、人物关系、外部局势或代价；默认落点为{result}。"
        ending_hook = f"章末钩子要具体指向下一步问题：{payoff}之后暴露的新限制、代价或外部动作。"
        no_repeat_guard = "禁止重复上一章的核心事件、同一试验目标、同一阻力逻辑、同类章末意象；不得回退已经获得的权限、资源、承诺或技术结论。"
        return {
            "title": title,
            "objective": f"{unique_task}\n{irreversible_change}",
            "plot_summary": f"{core_event}\n{tech_progression}\n{ending_hook}",
            "allowed_reveals": "只揭示本章角色已经看见、验证或付出代价得到的信息。",
            "forbidden_reveals": "禁止提前完成卷级/全书目标；禁止把已完成事项重新当作新目标。",
            "pace_limit": "从上一章结尾状态直接续写，先处理后果，再推进新行动，最后留下具体代价或钩子。",
            "unique_task": unique_task,
            "core_event": core_event,
            "tech_progression": tech_progression,
            "character_roles": character_roles,
            "antagonist_move": antagonist_move,
            "external_pressure": external_pressure,
            "irreversible_change": irreversible_change,
            "ending_hook": ending_hook,
            "no_repeat_guard": no_repeat_guard,
        }

    def delete_chapter(self, book_id: int, chapter_no: int) -> dict[str, Any]:
        with self.db.session() as conn:
            plan = self._fetchone(conn, "SELECT * FROM chapter_plans WHERE book_id = ? AND chapter_no = ?", (book_id, chapter_no)) or {}
            body = self._fetchone(conn, "SELECT * FROM chapter_bodies WHERE book_id = ? AND chapter_no = ?", (book_id, chapter_no)) or {}
            batch_id = plan.get("batch_id")
            exported = body.get("status") == "exported"
            for table in ["rework_tickets", "chapter_drafts", "editorial_decisions", "production_runs", "workflow_runs", "workflow_events", "construction_packets", "chapter_candidates", "rewrite_tasks", "pipeline_runs", "artifacts", "chapter_bodies", "chapter_plans"]:
                self._execute(conn, f"DELETE FROM {table} WHERE book_id = ? AND chapter_no = ?", (book_id, chapter_no))
            if exported:
                ph = self.db.placeholder()
                payload = json.dumps(json_safe({"chapter_no": chapter_no, "reason": "chapter_deleted_after_export"}), ensure_ascii=False)
                conn.cursor().execute(
                    f"INSERT INTO canonized_events (book_id, chapter_no, event_type, source_export_id, content) VALUES ({ph},{ph},{ph},{ph},{ph})",
                    (book_id, chapter_no, "chapter_retracted", body.get("export_id"), payload),
                )
            last_body = self._fetchone(conn, "SELECT MAX(chapter_no) AS chapter_no FROM chapter_bodies WHERE book_id = ?", (book_id,))
            self._execute(conn, "UPDATE books SET current_chapter_no = ? WHERE id = ?", (int((last_body or {}).get("chapter_no") or 0), book_id))
            self.log_event(conn, book_id, chapter_no, "chapter_deleted", "章节已删除；已导出连续性历史不会回滚。" if exported else "章节已删除，可重新生成。")
            return {"batch_id": batch_id, "exported": exported}

    def get_chapter_batch(self, batch_id: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT cb.*, v.title AS volume_title, a.title AS arc_title FROM chapter_batches cb LEFT JOIN volumes v ON v.id=cb.volume_id LEFT JOIN story_arcs a ON a.id=cb.arc_id WHERE cb.id = ?", (batch_id,))

    def list_chapter_batches(self, book_id: int) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            return self._fetchall(conn, "SELECT cb.*, v.title AS volume_title, a.title AS arc_title FROM chapter_batches cb LEFT JOIN volumes v ON v.id=cb.volume_id LEFT JOIN story_arcs a ON a.id=cb.arc_id WHERE cb.book_id = ? ORDER BY cb.id DESC", (book_id,))

    def update_batch_status(self, batch_id: int, status: str, message: str = "", error: str = "") -> None:
        with self.db.session() as conn:
            self._execute(conn, "UPDATE chapter_batches SET status = ?, progress_message = ?, error = ? WHERE id = ?", (status, message, error, batch_id))

    def get_architecture_context(self, book_id: int, chapter_no: int) -> dict[str, Any]:
        with self.db.session() as conn:
            plan = self._fetchone(conn, "SELECT * FROM chapter_plans WHERE book_id = ? AND chapter_no = ?", (book_id, chapter_no))
            if not plan:
                raise ValueError(f"chapter plan missing: book={book_id} chapter={chapter_no}")
            volume = self._fetchone(conn, "SELECT * FROM volumes WHERE id = ?", (plan["volume_id"],))
            arc = self._fetchone(conn, "SELECT * FROM story_arcs WHERE id = ?", (plan["arc_id"],))
            book = self._fetchone(conn, "SELECT * FROM books WHERE id = ?", (book_id,))
            style = self._fetchone(conn, "SELECT * FROM style_profiles WHERE book_id = ? AND locked = 1 ORDER BY id LIMIT 1", (book_id,))
            characters = self._fetchall(conn, "SELECT * FROM characters WHERE book_id = ? ORDER BY id", (book_id,))
            foreshadowings = self._fetchall(conn, "SELECT * FROM foreshadowings WHERE book_id = ? ORDER BY id", (book_id,))
            visibility = self._fetchall(conn, "SELECT * FROM visibility_rules WHERE book_id = ? ORDER BY id", (book_id,))
            canon = self._fetchall(conn, "SELECT * FROM canon_facts WHERE book_id = ? ORDER BY id", (book_id,))
            settings = self._fetchone(conn, "SELECT * FROM production_settings WHERE book_id = ?", (book_id,))
            author = self._fetchone(conn, "SELECT * FROM book_author_profiles WHERE id = ?", (book.get("book_author_profile_id") if book else None,))
            editor = self._fetchone(conn, "SELECT * FROM book_editor_profiles WHERE id = ?", (book.get("book_editor_profile_id") if book else None,))
        return {"book": book, "plan": plan, "volume": volume, "arc": arc, "style": style, "characters": characters, "foreshadowings": foreshadowings, "visibility": visibility, "canon": canon, "settings": settings or {}, "author_profile": author, "editor_profile": editor}

    def list_profiles(self, kind: str) -> list[dict[str, Any]]:
        table = "author_profiles" if kind == "authors" else "editor_profiles"
        with self.db.session() as conn:
            return self._fetchall(conn, f"SELECT * FROM {table} ORDER BY id")

    def get_profile(self, kind: str, profile_id: int) -> dict[str, Any] | None:
        table = "author_profiles" if kind == "authors" else "editor_profiles"
        with self.db.session() as conn:
            return self._fetchone(conn, f"SELECT * FROM {table} WHERE id = ?", (profile_id,))

    def save_profile(self, kind: str, data: dict[str, Any], profile_id: int | None = None) -> int:
        table = "author_profiles" if kind == "authors" else "editor_profiles"
        fields = ["name", "genre", "pov_preference", "sentence_rhythm", "dialogue_style", "payoff_preference", "forbidden_items", "prompt_rules"] if kind == "authors" else ["name", "platform", "word_count_rule", "pov_rule", "structure_rule", "payoff_rule", "pollution_rule", "reject_threshold"]
        clean = {field: data.get(field, "") for field in fields}
        if "reject_threshold" in clean:
            clean["reject_threshold"] = int(clean.get("reject_threshold") or 1)
        with self.db.session() as conn:
            ph = self.db.placeholder()
            if profile_id:
                assigns = ",".join([f"{field} = {ph}" for field in fields])
                self._execute(conn, f"UPDATE {table} SET {assigns} WHERE id = ?", (*clean.values(), profile_id))
                return profile_id
            cur = conn.cursor()
            cur.execute(f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join([ph] * len(fields))})", tuple(clean.values()))
            return self._last_id(cur)

    def assign_resources(self, book_id: int, author_profile_id: int, editor_profile_id: int) -> None:
        with self.db.session() as conn:
            book_author_id = self._clone_author_for_book(conn, book_id, author_profile_id)
            book_editor_id = self._clone_editor_for_book(conn, book_id, editor_profile_id)
            self._execute(conn, "UPDATE books SET author_profile_id = ?, editor_profile_id = ?, book_author_profile_id = ?, book_editor_profile_id = ? WHERE id = ?", (author_profile_id, editor_profile_id, book_author_id, book_editor_id, book_id))
            self.log_event(conn, book_id, None, "resources_assigned", "已为本书复制作者/编辑配置")

    def delete_profile(self, kind: str, profile_id: int) -> None:
        table = "author_profiles" if kind == "authors" else "editor_profiles"
        with self.db.session() as conn:
            self._execute(conn, f"DELETE FROM {table} WHERE id = ?", (profile_id,))

    def import_profiles(self, kind: str, json_text: str) -> list[int]:
        payload = json.loads(self._extract_json_payload(json_text))
        items = payload if isinstance(payload, list) else [payload]
        return [self.save_profile(kind, item) for item in items]

    def _extract_json_payload(self, text: str) -> str:
        cleaned = (text or "").strip().lstrip("\ufeff")
        if not cleaned:
            raise ValueError("JSON 内容为空。请粘贴单个 JSON 对象、JSON 数组，或 Markdown ```json 代码块。")
        fenced = re.search(r"```(?:json)?(?:\s+[^\n`]*)?\s*\n(?P<body>.*?)\n```", cleaned, flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            cleaned = fenced.group("body").strip()
        return cleaned

    def update_book_author_profile(self, book_id: int, data: dict[str, Any]) -> None:
        fields = ["name", "genre", "pov_preference", "sentence_rhythm", "dialogue_style", "payoff_preference", "forbidden_items", "prompt_rules", "sample_summary"]
        profile_id = self.get_book_controls(book_id)["book"]["book_author_profile_id"]
        with self.db.session() as conn:
            assigns = ",".join([f"{field} = ?" for field in fields])
            self._execute(conn, f"UPDATE book_author_profiles SET {assigns} WHERE id = ?", (*(data.get(field, "") for field in fields), profile_id))

    def update_book_editor_profile(self, book_id: int, data: dict[str, Any]) -> None:
        fields = ["name", "platform", "word_count_rule", "pov_rule", "structure_rule", "payoff_rule", "pollution_rule", "reject_threshold"]
        profile_id = self.get_book_controls(book_id)["book"]["book_editor_profile_id"]
        values = [data.get(field, "") for field in fields]
        values[-1] = int(values[-1] or 1)
        with self.db.session() as conn:
            assigns = ",".join([f"{field} = ?" for field in fields])
            self._execute(conn, f"UPDATE book_editor_profiles SET {assigns} WHERE id = ?", (*values, profile_id))

    def create_artifact(self, book_id: int, chapter_no: int | None, artifact_type: str, status: str, content: str, visibility: str = "internal") -> Artifact:
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(f"INSERT INTO artifacts (book_id, chapter_no, artifact_type, status, content, visibility) VALUES ({ph},{ph},{ph},{ph},{ph},{ph})", (book_id, chapter_no, artifact_type, status, content, visibility))
            artifact_id = self._last_id(cur)
            self.log_event(conn, book_id, chapter_no, ARTIFACT_LABELS.get(artifact_type, artifact_type), status)
        return Artifact(artifact_id, book_id, chapter_no, artifact_type, status, content)

    def get_artifact(self, artifact_id: int) -> Artifact | None:
        with self.db.session() as conn:
            row = self._fetchone(conn, "SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
        return Artifact(row["id"], row["book_id"], row["chapter_no"], row["artifact_type"], row["status"], row["content"]) if row else None

    def latest_artifact(self, book_id: int, chapter_no: int, artifact_type: str) -> Artifact | None:
        with self.db.session() as conn:
            row = self._fetchone(conn, "SELECT * FROM artifacts WHERE book_id = ? AND chapter_no = ? AND artifact_type = ? ORDER BY id DESC LIMIT 1", (book_id, chapter_no, artifact_type))
        return Artifact(row["id"], row["book_id"], row["chapter_no"], row["artifact_type"], row["status"], row["content"]) if row else None

    def list_artifacts(self, book_id: int, chapter_no: int | None = None) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            rows = self._fetchall(conn, "SELECT * FROM artifacts WHERE book_id = ? AND (? IS NULL OR chapter_no = ?) ORDER BY id DESC", (book_id, chapter_no, chapter_no))
        for row in rows:
            row["label"] = ARTIFACT_LABELS.get(row["artifact_type"], row["artifact_type"])
        return rows

    def create_run(self, book_id: int, chapter_no: int) -> int:
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(f"INSERT INTO pipeline_runs (book_id, chapter_no, status) VALUES ({ph},{ph},{ph})", (book_id, chapter_no, "running"))
            run_id = self._last_id(cur)
            self.log_event(conn, book_id, chapter_no, "生成正文", f"run={run_id}")
            return run_id

    def finish_run(self, run_id: int, book_id: int, chapter_no: int, status: str, error: str = "") -> None:
        with self.db.session() as conn:
            self._execute(conn, "UPDATE pipeline_runs SET status = ?, error = ? WHERE id = ?", (status, error, run_id))
            self.log_event(conn, book_id, chapter_no, "生成结束", status)

    def create_production_run(self, book_id: int, chapter_no: int, run_type: str = "chapter") -> int:
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(f"INSERT INTO production_runs (book_id, chapter_no, run_type, status) VALUES ({ph},{ph},{ph},{ph})", (book_id, chapter_no, run_type, "running"))
            run_id = self._last_id(cur)
            self.log_event(conn, book_id, chapter_no, "production_run_started", f"run={run_id}")
            return run_id

    def finish_production_run(self, run_id: int, book_id: int, chapter_no: int, status: str, failure_code: str = "", error: str = "") -> None:
        with self.db.session() as conn:
            self._execute(conn, "UPDATE production_runs SET status = ?, failure_code = ?, error = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ?", (status, failure_code, error, run_id))
            self.log_event(conn, book_id, chapter_no, "production_run_finished", status)

    def create_construction_packet(self, book_id: int, chapter_no: int, run_id: int | None, content: dict[str, Any]) -> dict[str, Any]:
        text = json.dumps(json_safe(content), ensure_ascii=False, indent=2)
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(f"INSERT INTO construction_packets (book_id, chapter_no, run_id, content) VALUES ({ph},{ph},{ph},{ph})", (book_id, chapter_no, run_id, text))
            return self._fetchone(conn, "SELECT * FROM construction_packets WHERE id = ?", (self._last_id(cur),)) or {}

    def get_construction_packet(self, packet_id: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT * FROM construction_packets WHERE id = ?", (packet_id,))

    def create_workflow_run(self, book_id: int, flow_name: str, chapter_no: int | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(
                f"INSERT INTO workflow_runs (book_id, chapter_no, flow_name, state, current_step, progress, payload) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
                (book_id, chapter_no, flow_name, "running", "started", 0, json.dumps(json_safe(payload or {}), ensure_ascii=False)),
            )
            run = self._fetchone(conn, "SELECT * FROM workflow_runs WHERE id = ?", (self._last_id(cur),)) or {}
            cur.execute(
                f"INSERT INTO workflow_events (run_id, book_id, chapter_no, event_type, message, payload) VALUES ({ph},{ph},{ph},{ph},{ph},{ph})",
                (int(run["id"]), book_id, chapter_no, f"{flow_name}_started", "工作流已启动", json.dumps(json_safe(payload or {}), ensure_ascii=False)),
            )
            return run

    def update_workflow_run(self, run_id: int, state: str, current_step: str = "", progress: int | None = None, error: str = "", payload: dict[str, Any] | None = None) -> None:
        with self.db.session() as conn:
            if state in {"completed", "failed", "blocked", "manual_required"}:
                self._execute(
                    conn,
                    "UPDATE workflow_runs SET state = ?, current_step = ?, progress = COALESCE(?, progress), error = ?, payload = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (state, current_step, progress, error, json.dumps(json_safe(payload or {}), ensure_ascii=False), run_id),
                )
            else:
                self._execute(
                    conn,
                    "UPDATE workflow_runs SET state = ?, current_step = ?, progress = COALESCE(?, progress), error = ?, payload = ? WHERE id = ?",
                    (state, current_step, progress, error, json.dumps(json_safe(payload or {}), ensure_ascii=False), run_id),
                )

    def create_workflow_event(self, run_id: int | None, book_id: int, chapter_no: int | None, event_type: str, message: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(
                f"INSERT INTO workflow_events (run_id, book_id, chapter_no, event_type, message, payload) VALUES ({ph},{ph},{ph},{ph},{ph},{ph})",
                (run_id, book_id, chapter_no, event_type, message, json.dumps(json_safe(payload or {}), ensure_ascii=False)),
            )
            return self._fetchone(conn, "SELECT * FROM workflow_events WHERE id = ?", (self._last_id(cur),)) or {}

    def list_workflow_runs(self, book_id: int, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            return self._fetchall(conn, "SELECT * FROM workflow_runs WHERE book_id = ? ORDER BY id DESC LIMIT ?", (book_id, limit))

    def list_workflow_events(self, book_id: int, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            return self._fetchall(conn, "SELECT * FROM workflow_events WHERE book_id = ? ORDER BY id DESC LIMIT ?", (book_id, limit))

    def upsert_chapter_candidate(self, book_id: int, chapter_no: int, work_order: dict[str, Any], volume_id: int | None = None, arc_id: int | None = None, status: str = "candidate", source: str = "planner", validation_errors: list[str] | None = None) -> dict[str, Any]:
        title = str(work_order.get("title") or f"第{chapter_no}章 待命名")
        text = json.dumps(json_safe(work_order), ensure_ascii=False, indent=2)
        errors = json.dumps(json_safe(validation_errors or []), ensure_ascii=False)
        with self.db.session() as conn:
            ph = self.db.placeholder()
            if self.db.is_mysql:
                sql = f"""INSERT INTO chapter_candidates
                    (book_id, volume_id, arc_id, chapter_no, title, work_order, status, validation_errors, source)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
                    ON DUPLICATE KEY UPDATE volume_id=VALUES(volume_id), arc_id=VALUES(arc_id), title=VALUES(title), work_order=VALUES(work_order), status=VALUES(status), validation_errors=VALUES(validation_errors), source=VALUES(source), updated_at=CURRENT_TIMESTAMP"""
            else:
                sql = f"""INSERT INTO chapter_candidates
                    (book_id, volume_id, arc_id, chapter_no, title, work_order, status, validation_errors, source)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
                    ON CONFLICT(book_id, chapter_no) DO UPDATE SET volume_id=excluded.volume_id, arc_id=excluded.arc_id, title=excluded.title, work_order=excluded.work_order, status=excluded.status, validation_errors=excluded.validation_errors, source=excluded.source, updated_at=CURRENT_TIMESTAMP"""
            conn.cursor().execute(sql, (book_id, volume_id, arc_id, chapter_no, title, text, status, errors, source))
            return self._fetchone(conn, "SELECT * FROM chapter_candidates WHERE book_id = ? AND chapter_no = ?", (book_id, chapter_no)) or {}

    def list_chapter_candidates(self, book_id: int, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            if status:
                return self._fetchall(conn, "SELECT * FROM chapter_candidates WHERE book_id = ? AND status = ? ORDER BY chapter_no LIMIT ?", (book_id, status, limit))
            return self._fetchall(conn, "SELECT * FROM chapter_candidates WHERE book_id = ? ORDER BY chapter_no LIMIT ?", (book_id, limit))

    def get_chapter_candidate(self, book_id: int, chapter_no: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT * FROM chapter_candidates WHERE book_id = ? AND chapter_no = ?", (book_id, chapter_no))

    def promote_candidate_to_task(self, book_id: int, chapter_no: int) -> dict[str, Any]:
        candidate = self.get_chapter_candidate(book_id, chapter_no)
        if not candidate:
            raise ValueError("chapter_candidate_missing")
        errors = json.loads(candidate.get("validation_errors") or "[]")
        if errors:
            raise ValueError("chapter_candidate_invalid: " + "; ".join(str(item) for item in errors))
        order = json.loads(candidate["work_order"])
        plan = self.get_chapter_plan_row(book_id, chapter_no)
        if not plan:
            with self.db.session() as conn:
                ph = self.db.placeholder()
                cur = conn.cursor()
                volume_id = int(candidate.get("volume_id") or 0)
                arc_id = int(candidate.get("arc_id") or 0)
                if not volume_id or not arc_id:
                    ctx = self._infer_current_outline_scope(conn, book_id, chapter_no)
                    volume_id = int(ctx["volume_id"])
                    arc_id = int(ctx["arc_id"])
                cur.execute(
                    f"""INSERT INTO chapter_plans
                    (book_id, volume_id, arc_id, chapter_no, title, objective, allowed_reveals, forbidden_reveals, pace_limit, plot_summary, target_chars, unique_task, core_event, tech_progression, character_roles, antagonist_move, external_pressure, irreversible_change, ending_hook, no_repeat_guard, status)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                    (
                        book_id, volume_id, arc_id, chapter_no, order.get("title", candidate["title"]),
                        order.get("mission", ""), order.get("allowed_reveals", ""), order.get("forbidden_future", ""),
                        order.get("opening_state", ""), order.get("scene_route", ""), order.get("target_chars", 2600),
                        order.get("mission", ""), order.get("core_event", ""), order.get("progression", ""),
                        order.get("character_roles", ""), order.get("antagonist_move", ""), order.get("external_pressure", ""),
                        order.get("irreversible_change", ""), order.get("handoff_to_next", ""), order.get("no_repeat_guard", ""), "task_ready",
                    ),
                )
        self.update_chapter_candidate_status(book_id, chapter_no, "promoted")
        return self.ensure_chapter_task(book_id, chapter_no)

    def update_chapter_candidate_status(self, book_id: int, chapter_no: int, status: str) -> None:
        with self.db.session() as conn:
            self._execute(conn, "UPDATE chapter_candidates SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE book_id = ? AND chapter_no = ?", (status, book_id, chapter_no))

    def _infer_current_outline_scope(self, conn: Any, book_id: int, chapter_no: int) -> dict[str, int]:
        arc = self._fetchone(conn, "SELECT * FROM story_arcs WHERE book_id = ? AND start_chapter <= ? AND end_chapter >= ? ORDER BY start_chapter LIMIT 1", (book_id, chapter_no, chapter_no))
        if not arc:
            arc = self._fetchone(conn, "SELECT * FROM story_arcs WHERE book_id = ? ORDER BY start_chapter LIMIT 1", (book_id,))
        if not arc:
            book = self._fetchone(conn, "SELECT * FROM books WHERE id = ?", (book_id,))
            self._seed_volumes_and_units(conn, book)
            arc = self._fetchone(conn, "SELECT * FROM story_arcs WHERE book_id = ? ORDER BY start_chapter LIMIT 1", (book_id,))
        return {"volume_id": int(arc["volume_id"]), "arc_id": int(arc["id"])}

    def create_chapter_draft(
        self,
        book_id: int,
        chapter_no: int,
        run_id: int | None,
        content: str,
        source_packet_id: int | None = None,
        rewrite_of_draft_id: int | None = None,
        status: str = "drafted",
    ) -> dict[str, Any]:
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(
                f"""INSERT INTO chapter_drafts
                (book_id, chapter_no, run_id, source_packet_id, rewrite_of_draft_id, status, content)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (book_id, chapter_no, run_id, source_packet_id, rewrite_of_draft_id, status, content),
            )
            draft = self._fetchone(conn, "SELECT * FROM chapter_drafts WHERE id = ?", (self._last_id(cur),)) or {}
            self.log_event(conn, book_id, chapter_no, "chapter_draft", status)
            return draft

    def get_chapter_draft(self, draft_id: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT * FROM chapter_drafts WHERE id = ?", (draft_id,))

    def latest_chapter_draft(self, book_id: int, chapter_no: int, status: str | None = None) -> dict[str, Any] | None:
        with self.db.session() as conn:
            if status:
                return self._fetchone(conn, "SELECT * FROM chapter_drafts WHERE book_id = ? AND chapter_no = ? AND status = ? ORDER BY id DESC LIMIT 1", (book_id, chapter_no, status))
            return self._fetchone(conn, "SELECT * FROM chapter_drafts WHERE book_id = ? AND chapter_no = ? ORDER BY id DESC LIMIT 1", (book_id, chapter_no))

    def list_chapter_drafts(self, book_id: int, chapter_no: int | None = None) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            return self._fetchall(conn, "SELECT * FROM chapter_drafts WHERE book_id = ? AND (? IS NULL OR chapter_no = ?) ORDER BY id DESC", (book_id, chapter_no, chapter_no))

    def create_rework_ticket(self, book_id: int, chapter_no: int, run_id: int | None, editorial_decision_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        failure_codes = payload.get("failure_codes") or []
        failure_code = ",".join(str(code) for code in failure_codes) if isinstance(failure_codes, list) else str(failure_codes or "")
        required = payload.get("required_fixes") or payload.get("evidence") or payload.get("problems") or []
        route = str(payload.get("route") or "writer")
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(
                f"""INSERT INTO rework_tickets
                (book_id, chapter_no, run_id, editorial_decision_id, route, failure_code, required_fixes, status, max_attempts)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (book_id, chapter_no, run_id, editorial_decision_id, route, failure_code, json.dumps(json_safe(required), ensure_ascii=False), "open", 2),
            )
            ticket = self._fetchone(conn, "SELECT * FROM rework_tickets WHERE id = ?", (self._last_id(cur),)) or {}
            self.log_event(conn, book_id, chapter_no, "rework_ticket", route)
            return ticket

    def get_rework_ticket(self, book_id: int, chapter_no: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT * FROM rework_tickets WHERE book_id = ? AND chapter_no = ? AND status IN ('open','running') ORDER BY id DESC LIMIT 1", (book_id, chapter_no))

    def list_rework_tickets(self, book_id: int, chapter_no: int | None = None) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            return self._fetchall(conn, "SELECT * FROM rework_tickets WHERE book_id = ? AND (? IS NULL OR chapter_no = ?) ORDER BY id DESC", (book_id, chapter_no, chapter_no))

    def update_rework_ticket(self, ticket_id: int, status: str, attempts: int | None = None) -> None:
        with self.db.session() as conn:
            if attempts is None:
                self._execute(conn, "UPDATE rework_tickets SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, ticket_id))
            else:
                self._execute(conn, "UPDATE rework_tickets SET status = ?, attempts = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, attempts, ticket_id))

    def list_editorial_decisions(self, book_id: int, chapter_no: int | None = None) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            return self._fetchall(conn, "SELECT * FROM editorial_decisions WHERE book_id = ? AND (? IS NULL OR chapter_no = ?) ORDER BY id DESC", (book_id, chapter_no, chapter_no))

    def create_ledger_candidate(
        self,
        book_id: int,
        chapter_no: int | None,
        ledger_type: str,
        subject_key: str,
        content: Any,
        source_export_id: int | None = None,
        source_snapshot_id: int | None = None,
        supersedes_id: int | None = None,
        status: str = "candidate",
    ) -> dict[str, Any]:
        text = content if isinstance(content, str) else json.dumps(json_safe(content), ensure_ascii=False, indent=2)
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(
                f"""INSERT INTO ledger_update_candidates
                (book_id, chapter_no, ledger_type, subject_key, content, status, source_export_id, source_snapshot_id, supersedes_id)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (book_id, chapter_no, ledger_type, subject_key, text, status, source_export_id, source_snapshot_id, supersedes_id),
            )
            return self._fetchone(conn, "SELECT * FROM ledger_update_candidates WHERE id = ?", (self._last_id(cur),)) or {}

    def list_ledger_candidates(self, book_id: int, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            if status:
                return self._fetchall(conn, "SELECT * FROM ledger_update_candidates WHERE book_id = ? AND status = ? ORDER BY id DESC LIMIT ?", (book_id, status, limit))
            return self._fetchall(conn, "SELECT * FROM ledger_update_candidates WHERE book_id = ? ORDER BY id DESC LIMIT ?", (book_id, limit))

    def list_snapshots(self, book_id: int, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            return self._fetchall(conn, "SELECT * FROM chapter_state_snapshots WHERE book_id = ? ORDER BY chapter_no DESC, version DESC LIMIT ?", (book_id, limit))

    def list_official_canon(self, book_id: int, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            return self._fetchall(conn, "SELECT * FROM official_canon WHERE book_id = ? ORDER BY id DESC LIMIT ?", (book_id, limit))

    def list_ledger_entries(self, book_id: int, table: str, limit: int = 100) -> list[dict[str, Any]]:
        allowed = {"character_states", "relationship_states", "foreshadowing_ledger", "setting_ledger", "progression_ledger"}
        if table not in allowed:
            raise ValueError("unknown ledger table")
        with self.db.session() as conn:
            return self._fetchall(conn, f"SELECT * FROM {table} WHERE book_id = ? ORDER BY id DESC LIMIT ?", (book_id, limit))

    def list_recent_transitions(self, book_id: int, before_chapter_no: int, limit: int = 3) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            return self._fetchall(conn, "SELECT * FROM chapter_transitions WHERE book_id = ? AND chapter_no < ? ORDER BY chapter_no DESC LIMIT ?", (book_id, before_chapter_no, limit))

    def ensure_chapter_task(self, book_id: int, chapter_no: int) -> dict[str, Any]:
        plan = self.get_chapter_plan_row(book_id, chapter_no)
        if not plan:
            raise ValueError("章节任务缺少细纲，无法进入生产状态机。")
        with self.db.session() as conn:
            current = self._fetchone(conn, "SELECT * FROM chapter_tasks WHERE book_id = ? AND chapter_no = ? ORDER BY revision DESC LIMIT 1", (book_id, chapter_no))
            payload = self._chapter_task_payload(plan)
            ph = self.db.placeholder()
            if current:
                self._execute(
                    conn,
                    "UPDATE chapter_tasks SET opening_state = ?, mission = ?, definition_of_done = ?, scene_route = ?, irreversible_change = ?, handoff_to_next = ?, forbidden_future = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (payload["opening_state"], payload["mission"], payload["definition_of_done"], payload["scene_route"], payload["irreversible_change"], payload["handoff_to_next"], payload["forbidden_future"], current["id"]),
                )
                return self._fetchone(conn, "SELECT * FROM chapter_tasks WHERE id = ?", (current["id"],)) or current
            cur = conn.cursor()
            cur.execute(
                f"""INSERT INTO chapter_tasks
                (book_id, chapter_no, status, opening_state, mission, definition_of_done, scene_route, irreversible_change, handoff_to_next, forbidden_future, revision, source_plan_id)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (book_id, chapter_no, "task_ready", payload["opening_state"], payload["mission"], payload["definition_of_done"], payload["scene_route"], payload["irreversible_change"], payload["handoff_to_next"], payload["forbidden_future"], 1, plan.get("id")),
            )
            return self._fetchone(conn, "SELECT * FROM chapter_tasks WHERE id = ?", (self._last_id(cur),)) or {}

    def _chapter_task_payload(self, plan: dict[str, Any]) -> dict[str, str]:
        return {
            "opening_state": str(plan.get("pace_limit") or "从上一章结尾状态直接续写。"),
            "mission": str(plan.get("unique_task") or plan.get("objective") or ""),
            "definition_of_done": json.dumps(
                json_safe(
                    [
                        plan.get("core_event") or plan.get("plot_summary") or "",
                        plan.get("irreversible_change") or "",
                        plan.get("ending_hook") or "",
                    ]
                ),
                ensure_ascii=False,
            ),
            "scene_route": str(plan.get("plot_summary") or plan.get("core_event") or ""),
            "irreversible_change": str(plan.get("irreversible_change") or ""),
            "handoff_to_next": str(plan.get("ending_hook") or ""),
            "forbidden_future": str(plan.get("forbidden_reveals") or plan.get("no_repeat_guard") or ""),
        }

    def set_chapter_task_status(self, book_id: int, chapter_no: int, status: str) -> None:
        with self.db.session() as conn:
            self._execute(conn, "UPDATE chapter_tasks SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE book_id = ? AND chapter_no = ?", (status, book_id, chapter_no))
            self.log_event(conn, book_id, chapter_no, "chapter_task_status", status)

    def get_chapter_task(self, book_id: int, chapter_no: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT * FROM chapter_tasks WHERE book_id = ? AND chapter_no = ? ORDER BY revision DESC LIMIT 1", (book_id, chapter_no))

    def get_active_chapter_task(self, book_id: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT * FROM chapter_tasks WHERE book_id = ? AND status IN ('drafting','editorial_review','rewrite_needed','editorial_passed','human_release_check') ORDER BY chapter_no LIMIT 1", (book_id,))

    def assert_can_enter_drafting(self, book_id: int, chapter_no: int) -> None:
        active = self.get_active_chapter_task(book_id)
        if active and int(active.get("chapter_no") or 0) != int(chapter_no):
            raise ValueError(f"当前第 {active.get('chapter_no')} 章仍在生产中，请先完成或人工处理后再生成新章节。")
        if chapter_no <= 1:
            return
        previous = self.get_chapter_body(book_id, chapter_no - 1)
        if not previous:
            raise ValueError(f"第 {chapter_no - 1} 章尚无可承接正文，第 {chapter_no} 章不能进入正式写作。")

    def assert_can_enter_drafting(self, book_id: int, chapter_no: int) -> None:
        active = self.get_active_chapter_task(book_id)
        if active and int(active.get("chapter_no") or 0) != int(chapter_no):
            raise ValueError(f"active_chapter_conflict: chapter {active.get('chapter_no')} is still active.")
        task = self.ensure_chapter_task(book_id, chapter_no)
        if str(task.get("status") or "") not in {"task_ready", "rewrite_needed"}:
            raise ValueError(f"task_not_ready: chapter {chapter_no} is {task.get('status')}.")
        if chapter_no <= 1:
            return
        previous = self.get_chapter_body(book_id, chapter_no - 1)
        if not previous or str(previous.get("status") or "") not in {"exported", "published", "canonized"}:
            raise ValueError(f"previous_not_published: chapter {chapter_no - 1} must be published before chapter {chapter_no} enters drafting.")

    def create_editorial_decision(
        self,
        book_id: int,
        chapter_no: int,
        decision: str,
        review_artifact_id: int | None = None,
        run_id: int | None = None,
        payload: dict[str, Any] | None = None,
        draft_id: int | None = None,
    ) -> dict[str, Any]:
        payload = payload or {}
        problems = payload.get("problems") or payload.get("blocking_issues") or payload.get("notes") or []
        codes = payload.get("failure_codes") or []
        failure_code = "approved" if decision == "approved" else (",".join(str(code) for code in codes) if codes else self._failure_code_from_review(payload))
        route = payload.get("route") or ("writer" if decision in {"rejected", "rewrite"} else ("human" if decision == "manual" else ""))
        score = safe_int_field(payload.get("score"), 100 if decision == "approved" else 0, 0, 100, "score")
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(
                f"""INSERT INTO editorial_decisions
                (book_id, chapter_no, run_id, review_artifact_id, draft_id, decision, score, failure_code, route, evidence, required_fixes, retryable)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (
                    book_id,
                    chapter_no,
                    run_id,
                    review_artifact_id,
                    draft_id,
                    decision,
                    score,
                    failure_code,
                    route,
                    json.dumps(json_safe(payload.get("evidence") or problems), ensure_ascii=False),
                    json.dumps(json_safe(payload.get("required_fixes") or payload), ensure_ascii=False),
                    1 if decision != "approved" else 0,
                ),
            )
            return self._fetchone(conn, "SELECT * FROM editorial_decisions WHERE id = ?", (self._last_id(cur),)) or {}

    def _failure_code_from_review(self, payload: dict[str, Any]) -> str:
        text = json.dumps(json_safe(payload), ensure_ascii=False)
        if "连续性" in text or "回退" in text:
            return "continuity_conflict"
        if "字数" in text:
            return "word_count"
        if "污染" in text or "部门" in text:
            return "meta_pollution"
        if "纲" in text or "任务" in text:
            return "plan_misalignment"
        return "editorial_rewrite"

    def create_rewrite_task(self, book_id: int, chapter_no: int, review_artifact_id: int, error: str = "") -> dict[str, Any]:
        with self.db.session() as conn:
            existing = self._fetchone(conn, "SELECT * FROM rewrite_tasks WHERE book_id = ? AND chapter_no = ? AND status IN ('pending','running') ORDER BY id DESC LIMIT 1", (book_id, chapter_no))
            if existing:
                self._execute(conn, "UPDATE rewrite_tasks SET review_artifact_id = ?, error = ? WHERE id = ?", (review_artifact_id, error, existing["id"]))
                return self._fetchone(conn, "SELECT * FROM rewrite_tasks WHERE id = ?", (existing["id"],)) or existing
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(f"INSERT INTO rewrite_tasks (book_id, chapter_no, review_artifact_id, max_attempts, error) VALUES ({ph},{ph},{ph},{ph},{ph})", (book_id, chapter_no, review_artifact_id, 3, error))
            return self._fetchone(conn, "SELECT * FROM rewrite_tasks WHERE id = ?", (self._last_id(cur),)) or {}

    def get_rewrite_task(self, book_id: int, chapter_no: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT * FROM rewrite_tasks WHERE book_id = ? AND chapter_no = ? ORDER BY id DESC LIMIT 1", (book_id, chapter_no))

    def update_rewrite_task(self, task_id: int, status: str, attempts: int | None = None, error: str = "") -> None:
        with self.db.session() as conn:
            if attempts is None:
                self._execute(conn, "UPDATE rewrite_tasks SET status = ?, error = ? WHERE id = ?", (status, error, task_id))
            else:
                self._execute(conn, "UPDATE rewrite_tasks SET status = ?, attempts = ?, error = ? WHERE id = ?", (status, attempts, error, task_id))

    def resolve_generation_errors(self, book_id: int, chapter_no: int) -> None:
        with self.db.session() as conn:
            self._execute(conn, "UPDATE artifacts SET status = ? WHERE book_id = ? AND chapter_no = ? AND artifact_type = ? AND status = ?", ("resolved", book_id, chapter_no, "generation_error", "failed"))

    def resolve_generation_errors_for_existing_bodies(self) -> None:
        with self.db.session() as conn:
            if self.db.is_mysql:
                sql = """UPDATE artifacts a
                    JOIN chapter_bodies b ON b.book_id = a.book_id AND b.chapter_no = a.chapter_no
                    SET a.status = %s
                    WHERE a.artifact_type = %s AND a.status = %s"""
            else:
                sql = """UPDATE artifacts
                    SET status = ?
                    WHERE artifact_type = ? AND status = ?
                    AND EXISTS (
                        SELECT 1 FROM chapter_bodies
                        WHERE chapter_bodies.book_id = artifacts.book_id
                        AND chapter_bodies.chapter_no = artifacts.chapter_no
                    )"""
            conn.cursor().execute(sql, ("resolved", "generation_error", "failed"))

    def save_chapter_body(self, book_id: int, chapter_no: int, title: str, body: str, status: str = "drafted", export_id: int | None = None) -> None:
        with self.db.session() as conn:
            ph = self.db.placeholder()
            if self.db.is_mysql:
                sql = f"""INSERT INTO chapter_bodies (book_id, chapter_no, title, body, status, export_id)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph})
                    ON DUPLICATE KEY UPDATE title=VALUES(title), body=VALUES(body), status=VALUES(status), export_id=VALUES(export_id)"""
            else:
                sql = f"""INSERT INTO chapter_bodies (book_id, chapter_no, title, body, status, export_id)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph})
                    ON CONFLICT(book_id, chapter_no) DO UPDATE SET title=excluded.title, body=excluded.body, status=excluded.status, export_id=excluded.export_id"""
            conn.cursor().execute(sql, (book_id, chapter_no, title, body, status, export_id))
            self.log_event(conn, book_id, chapter_no, "正文状态", status)

    def get_chapter_body(self, book_id: int, chapter_no: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT * FROM chapter_bodies WHERE book_id = ? AND chapter_no = ?", (book_id, chapter_no))

    def list_chapter_bodies(self, book_id: int, status: str | None = None) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            if status:
                return self._fetchall(conn, "SELECT * FROM chapter_bodies WHERE book_id = ? AND status = ? ORDER BY chapter_no", (book_id, status))
            return self._fetchall(conn, "SELECT * FROM chapter_bodies WHERE book_id = ? ORDER BY chapter_no", (book_id,))

    def confirm_chapter_body(self, book_id: int, chapter_no: int, body: str | None = None) -> None:
        current = self.get_chapter_body(book_id, chapter_no)
        if not current:
            raise ValueError("没有可确认的正文。")
        self.save_chapter_body(book_id, chapter_no, current["title"], body if body is not None else current["body"], "human_confirmed", current.get("export_id"))

    def create_export_record(self, book_id: int, export_type: str, file_path: str, status: str = "ready") -> dict[str, Any]:
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(f"INSERT INTO export_records (book_id, export_type, file_path, status) VALUES ({ph},{ph},{ph},{ph})", (book_id, export_type, file_path, status))
            row = self._fetchone(conn, "SELECT * FROM export_records WHERE id = ?", (self._last_id(cur),)) or {}
            self.log_event(conn, book_id, None, "导出", file_path)
            return row

    def mark_exported(self, book_id: int, export_id: int) -> None:
        with self.db.session() as conn:
            self._execute(conn, "UPDATE chapter_bodies SET status = ?, export_id = ? WHERE book_id = ? AND status = ?", ("exported", export_id, book_id, "human_confirmed"))

    def confirm_chapter_body(self, book_id: int, chapter_no: int, body: str | None = None) -> None:
        current = self.get_chapter_body(book_id, chapter_no)
        if not current:
            raise ValueError("No chapter body can be confirmed.")
        final_body = body if body is not None else current["body"]
        self.save_chapter_body(book_id, chapter_no, current["title"], final_body, "human_confirmed", current.get("export_id"))
        self.create_human_approval_log(book_id, chapter_no, "human_confirmed", final_body)
        self.set_chapter_task_status(book_id, chapter_no, "human_release_check")

    def create_human_approval_log(self, book_id: int, chapter_no: int, decision: str, body: str, note: str = "") -> dict[str, Any]:
        import hashlib

        body_hash = hashlib.sha256((body or "").encode("utf-8")).hexdigest()
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(f"INSERT INTO human_approval_logs (book_id, chapter_no, decision, body_hash, note) VALUES ({ph},{ph},{ph},{ph},{ph})", (book_id, chapter_no, decision, body_hash, note))
            return self._fetchone(conn, "SELECT * FROM human_approval_logs WHERE id = ?", (self._last_id(cur),)) or {}

    def mark_exported(self, book_id: int, export_id: int) -> None:
        with self.db.session() as conn:
            self._execute(conn, "UPDATE chapter_bodies SET status = ?, export_id = ? WHERE book_id = ? AND status = ?", ("exported", export_id, book_id, "human_confirmed"))
        for row in [item for item in self.list_chapter_bodies(book_id, status="exported") if int(item.get("export_id") or 0) == int(export_id)]:
            self.publish_chapter(book_id, int(row["chapter_no"]), int(export_id), row)
        self.create_export_version(book_id, export_id)

    def create_export_version(self, book_id: int, export_id: int) -> dict[str, Any]:
        import hashlib

        bodies = [row for row in self.list_chapter_bodies(book_id, status="exported") if int(row.get("export_id") or 0) == int(export_id)]
        source = [int(row["chapter_no"]) for row in bodies]
        digest = hashlib.sha256("\n\n".join(str(row.get("body") or "") for row in bodies).encode("utf-8")).hexdigest()
        with self.db.session() as conn:
            old = self._fetchone(conn, "SELECT MAX(version) AS version FROM export_versions WHERE book_id = ?", (book_id,))
            version = int((old or {}).get("version") or 0) + 1
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(
                f"INSERT INTO export_versions (book_id, export_id, version, status, body_hash, source_chapters) VALUES ({ph},{ph},{ph},{ph},{ph},{ph})",
                (book_id, export_id, version, "published", digest, json.dumps(source)),
            )
            return self._fetchone(conn, "SELECT * FROM export_versions WHERE id = ?", (self._last_id(cur),)) or {}

    def list_export_versions(self, book_id: int | None = None) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            if book_id:
                return self._fetchall(conn, "SELECT * FROM export_versions WHERE book_id = ? ORDER BY version DESC", (book_id,))
            return self._fetchall(conn, "SELECT * FROM export_versions ORDER BY id DESC")

    def publish_chapter(self, book_id: int, chapter_no: int, export_id: int, body_row: dict[str, Any] | None = None) -> None:
        body_row = body_row or self.get_chapter_body(book_id, chapter_no)
        if not body_row:
            return
        plan = self.get_chapter_plan_row(book_id, chapter_no) or {}
        closing = str(body_row.get("body") or "")[-1200:]
        transition = {
            "chapter_no": chapter_no,
            "title": body_row.get("title") or plan.get("title") or f"Chapter {chapter_no}",
            "mission": plan.get("unique_task") or plan.get("objective") or "",
            "irreversible_change": plan.get("irreversible_change") or "",
            "ending_hook": plan.get("ending_hook") or "",
        }
        with self.db.session() as conn:
            old_snapshot = self._fetchone(conn, "SELECT id, version FROM chapter_state_snapshots WHERE book_id = ? AND chapter_no = ? ORDER BY version DESC, id DESC LIMIT 1", (book_id, chapter_no))
            old_transition = self._fetchone(conn, "SELECT id, version FROM chapter_transitions WHERE book_id = ? AND chapter_no = ? ORDER BY version DESC, id DESC LIMIT 1", (book_id, chapter_no))
            old_canon = self._fetchone(conn, "SELECT id, version FROM official_canon WHERE book_id = ? AND chapter_no = ? AND canon_type = ? ORDER BY version DESC, id DESC LIMIT 1", (book_id, chapter_no, "published_chapter_transition"))
            version = int((old_snapshot or {}).get("version") or 0) + 1
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(
                f"""INSERT INTO chapter_state_snapshots
                (book_id, chapter_no, status, opening_state, closing_state, unit_state, style_signature, source_export_id, supersedes_snapshot_id, version, snapshot_json)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (
                    book_id,
                    chapter_no,
                    "published",
                    plan.get("pace_limit") or "",
                    closing,
                    json.dumps(json_safe({"volume": plan.get("volume_title"), "unit": plan.get("arc_title")}), ensure_ascii=False),
                    "",
                    export_id,
                    (old_snapshot or {}).get("id"),
                    version,
                    json.dumps(json_safe({"plan": plan, "transition": transition}), ensure_ascii=False, indent=2),
                ),
            )
            snapshot_id = self._last_id(cur)
            cur.execute(
                f"""INSERT INTO chapter_transitions
                (book_id, chapter_no, from_state, to_state, transition_summary, source_export_id, supersedes_transition_id, version)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (book_id, chapter_no, "human_release_check", "published", json.dumps(json_safe(transition), ensure_ascii=False), export_id, (old_transition or {}).get("id"), version),
            )
            transition_id = self._last_id(cur)
            cur.execute(
                f"""INSERT INTO official_canon
                (book_id, chapter_no, canon_type, content, source_export_id, source_event_id, source_snapshot_id, supersedes_canon_id, version, status)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (book_id, chapter_no, "published_chapter_transition", json.dumps(json_safe(transition), ensure_ascii=False), export_id, transition_id, snapshot_id, (old_canon or {}).get("id"), version, "published"),
            )
            cur.execute(
                f"""INSERT INTO canonized_events
                (book_id, chapter_no, event_type, source_export_id, content)
                VALUES ({ph},{ph},{ph},{ph},{ph})""",
                (book_id, chapter_no, "chapter_published", export_id, json.dumps(json_safe({"snapshot_id": snapshot_id, "transition_id": transition_id}), ensure_ascii=False)),
            )
            cur.execute(
                f"""INSERT INTO ledger_update_candidates
                (book_id, chapter_no, ledger_type, subject_key, content, status, source_export_id, source_snapshot_id)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (book_id, chapter_no, "chapter_transition", f"chapter:{chapter_no}", json.dumps(json_safe(transition), ensure_ascii=False, indent=2), "candidate", export_id, snapshot_id),
            )
            cur.execute(
                f"""INSERT INTO continuity_atoms
                (book_id, chapter_no, atom_type, content, status, visible_after_chapter, source_ref, source_export_id, subject_key, confidence)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (book_id, chapter_no, "chapter_published_fact", json.dumps(json_safe(transition), ensure_ascii=False), "candidate", chapter_no, f"export:{export_id}", export_id, f"chapter:{chapter_no}", 0.78),
            )
            self._execute(conn, "UPDATE chapter_tasks SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE book_id = ? AND chapter_no = ?", ("published", book_id, chapter_no))

    def backfill_phase2_ledgers(self, book_id: int | None = None) -> int:
        created = 0
        with self.db.session() as conn:
            if book_id:
                bodies = self._fetchall(conn, "SELECT * FROM chapter_bodies WHERE book_id = ? AND status IN ('exported','published','canonized') ORDER BY chapter_no", (book_id,))
            else:
                bodies = self._fetchall(conn, "SELECT * FROM chapter_bodies WHERE status IN ('exported','published','canonized') ORDER BY book_id, chapter_no")
        for body in bodies:
            export_id = int(body.get("export_id") or 0)
            if not export_id:
                continue
            exists = None
            with self.db.session() as conn:
                exists = self._fetchone(conn, "SELECT id FROM chapter_state_snapshots WHERE book_id = ? AND chapter_no = ? AND source_export_id = ? LIMIT 1", (body["book_id"], body["chapter_no"], export_id))
            if exists:
                continue
            self.publish_chapter(int(body["book_id"]), int(body["chapter_no"]), export_id, body)
            created += 1
        return created

    def rollback_snapshot(self, book_id: int, snapshot_id: int, note: str = "") -> dict[str, Any]:
        with self.db.session() as conn:
            snapshot = self._fetchone(conn, "SELECT * FROM chapter_state_snapshots WHERE id = ? AND book_id = ?", (snapshot_id, book_id))
            if not snapshot:
                raise ValueError("snapshot not found")
            cur = conn.cursor()
            ph = self.db.placeholder()
            payload = {"rollback_to_snapshot_id": snapshot_id, "chapter_no": snapshot.get("chapter_no"), "note": note}
            cur.execute(
                f"INSERT INTO canonized_events (book_id, chapter_no, event_type, source_export_id, content) VALUES ({ph},{ph},{ph},{ph},{ph})",
                (book_id, snapshot.get("chapter_no"), "snapshot_rollback", snapshot.get("source_export_id"), json.dumps(json_safe(payload), ensure_ascii=False)),
            )
            event_id = self._last_id(cur)
            cur.execute(
                f"""INSERT INTO ledger_update_candidates
                (book_id, chapter_no, ledger_type, subject_key, content, status, source_export_id, source_snapshot_id)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (book_id, snapshot.get("chapter_no"), "rollback_marker", f"snapshot:{snapshot_id}", json.dumps(json_safe(payload), ensure_ascii=False), "candidate", snapshot.get("source_export_id"), snapshot_id),
            )
            return self._fetchone(conn, "SELECT * FROM canonized_events WHERE id = ?", (event_id,)) or {}

    def list_exports(self, book_id: int | None = None) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            if book_id:
                return self._fetchall(conn, "SELECT * FROM export_records WHERE book_id = ? ORDER BY id DESC", (book_id,))
            return self._fetchall(conn, "SELECT e.*, b.title AS book_title FROM export_records e LEFT JOIN books b ON b.id = e.book_id ORDER BY e.id DESC")

    def create_memory(self, book_id: int, memory_type: str, scope_key: str, content: dict[str, Any] | str, start: int | None = None, end: int | None = None, source_export_id: int | None = None, token_budget: int = 1200) -> dict[str, Any]:
        text = json.dumps(json_safe(content), ensure_ascii=False, indent=2) if not isinstance(content, str) else content
        with self.db.session() as conn:
            old = self._fetchone(conn, "SELECT MAX(version) AS version FROM continuity_memories WHERE book_id = ? AND memory_type = ? AND scope_key = ?", (book_id, memory_type, scope_key))
            version = int((old or {}).get("version") or 0) + 1
            self._execute(conn, "UPDATE continuity_memories SET is_current = 0 WHERE book_id = ? AND memory_type = ? AND scope_key = ?", (book_id, memory_type, scope_key))
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(f"""INSERT INTO continuity_memories
                (book_id, memory_type, scope_key, version, source_export_id, source_start_chapter, source_end_chapter, is_current, compression_mode, token_budget, content)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""", (book_id, memory_type, scope_key, version, source_export_id, start, end, 1, "structured_budget", token_budget, text))
            return self._fetchone(conn, "SELECT * FROM continuity_memories WHERE id = ?", (self._last_id(cur),)) or {}

    def list_memories(self, book_id: int, memory_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            if memory_type:
                return self._fetchall(conn, "SELECT * FROM continuity_memories WHERE book_id = ? AND memory_type = ? ORDER BY id DESC LIMIT ?", (book_id, memory_type, limit))
            return self._fetchall(conn, "SELECT * FROM continuity_memories WHERE book_id = ? ORDER BY id DESC LIMIT ?", (book_id, limit))

    def latest_memory(self, book_id: int, memory_type: str, scope_key: str) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT * FROM continuity_memories WHERE book_id = ? AND memory_type = ? AND scope_key = ? AND is_current = 1 ORDER BY version DESC LIMIT 1", (book_id, memory_type, scope_key))

    def update_memory_content(self, memory_id: int, content: str) -> dict[str, Any]:
        with self.db.session() as conn:
            old = self._fetchone(conn, "SELECT * FROM continuity_memories WHERE id = ?", (memory_id,))
            if not old:
                raise ValueError("记忆不存在。")
        return self.create_memory(old["book_id"], old["memory_type"], old["scope_key"], content, old["source_start_chapter"], old["source_end_chapter"], old.get("source_export_id"), old.get("token_budget") or 1200)

    def create_atom(self, book_id: int, chapter_no: int | None, atom_type: str, content: str, status: str = "candidate", visible_after_chapter: int = 0, source_ref: str = "", source_export_id: int | None = None, characters: str = "", foreshadowing_tags: str = "", confidence: float = 0.6) -> dict[str, Any]:
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(f"""INSERT INTO continuity_atoms
                (book_id, chapter_no, atom_type, content, status, visible_after_chapter, source_ref, source_export_id, characters, foreshadowing_tags, confidence)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""", (book_id, chapter_no, atom_type, content, status, visible_after_chapter, source_ref, source_export_id, characters, foreshadowing_tags, confidence))
            return self._fetchone(conn, "SELECT * FROM continuity_atoms WHERE id = ?", (self._last_id(cur),)) or {}

    def list_atoms(self, book_id: int, status: str | None = None, chapter_no: int | None = None) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            if chapter_no is not None:
                return self._fetchall(conn, "SELECT * FROM continuity_atoms WHERE book_id = ? AND chapter_no = ? ORDER BY id DESC", (book_id, chapter_no))
            if status:
                return self._fetchall(conn, "SELECT * FROM continuity_atoms WHERE book_id = ? AND status = ? ORDER BY id DESC", (book_id, status))
            return self._fetchall(conn, "SELECT * FROM continuity_atoms WHERE book_id = ? ORDER BY id DESC", (book_id,))

    def update_atom_status(self, atom_id: int, status: str) -> None:
        with self.db.session() as conn:
            self._execute(conn, "UPDATE continuity_atoms SET status = ? WHERE id = ?", (status, atom_id))

    def create_retrieval_log(self, book_id: int, chapter_no: int, query: str, memory_ids: list[int], atom_ids: list[int], reason: str, run_id: int | None = None) -> dict[str, Any]:
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(f"INSERT INTO memory_retrieval_logs (book_id, run_id, chapter_no, query, selected_memory_ids, selected_atom_ids, reason) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})", (book_id, run_id, chapter_no, query, json.dumps(memory_ids), json.dumps(atom_ids), reason))
            return self._fetchone(conn, "SELECT * FROM memory_retrieval_logs WHERE id = ?", (self._last_id(cur),)) or {}

    def list_retrieval_logs(self, book_id: int) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            return self._fetchall(conn, "SELECT * FROM memory_retrieval_logs WHERE book_id = ? ORDER BY id DESC", (book_id,))

    def create_drift_report(self, book_id: int, chapter_no: int | None, content: dict[str, Any]) -> dict[str, Any]:
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(f"INSERT INTO drift_reports (book_id, chapter_no, content) VALUES ({ph},{ph},{ph})", (book_id, chapter_no, json.dumps(json_safe(content), ensure_ascii=False, indent=2)))
            return self._fetchone(conn, "SELECT * FROM drift_reports WHERE id = ?", (self._last_id(cur),)) or {}

    def list_drift_reports(self, book_id: int) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            return self._fetchall(conn, "SELECT * FROM drift_reports WHERE book_id = ? ORDER BY id DESC", (book_id,))

    def list_events(self, book_id: int, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            return self._fetchall(conn, "SELECT * FROM events WHERE book_id = ? ORDER BY id DESC LIMIT ?", (book_id, limit))

    def log_event(self, conn: Any, book_id: int, chapter_no: int | None, event_type: str, message: str) -> None:
        ph = self.db.placeholder()
        conn.cursor().execute(f"INSERT INTO events (book_id, chapter_no, event_type, message) VALUES ({ph},{ph},{ph},{ph})", (book_id, chapter_no, event_type, message))

    def dashboard(self) -> dict[str, Any]:
        self.ensure_default_resources()
        books = self.list_books("active")
        shelf = []
        for book in books:
            record = self.get_book_record(book.id) or {}
            bodies = self.list_chapter_bodies(book.id)
            latest = bodies[-1] if bodies else None
            shelf.append({"book": book, "record": record, "latest": latest, "total_chars": sum(len("".join(row["body"].split())) for row in bodies)})
        return {"books": books, "shelf": shelf}

    def book_workbench(self, book_id: int) -> dict[str, Any]:
        book = self.get_book_record(book_id)
        if not book:
            return {}
        bodies = self.list_chapter_bodies(book_id)
        latest_body = bodies[-1] if bodies else None
        active = self.get_active_chapter_task(book_id)
        candidates = self.list_chapter_candidates(book_id, limit=12)
        open_tickets = [row for row in self.list_rework_tickets(book_id) if row.get("status") in {"open", "running", "manual_required"}][:8]
        snapshots = self.list_snapshots(book_id, 8)
        canon = self.list_official_canon(book_id, 8)
        ledger_candidates = self.list_ledger_candidates(book_id, status="candidate", limit=12)
        workflows = self.list_workflow_runs(book_id, 10)
        publish_ready = [row for row in bodies if row.get("status") in {"human_confirmed"}]
        editor_passed = [row for row in bodies if row.get("status") == "editor_approved"]
        return {
            "book": book,
            "latest_body": latest_body,
            "total_chapters": len(bodies),
            "total_chars": sum(len("".join(str(row.get("body") or "").split())) for row in bodies),
            "active_task": active,
            "candidates": candidates,
            "open_tickets": open_tickets,
            "recent_snapshots": snapshots,
            "recent_canon": canon,
            "ledger_candidates": ledger_candidates,
            "workflow_runs": workflows,
            "publish_ready": publish_ready,
            "editor_passed": editor_passed,
            "next_action": self._next_workbench_action(active, candidates, open_tickets, publish_ready, editor_passed),
        }

    def _next_workbench_action(self, active: dict[str, Any] | None, candidates: list[dict[str, Any]], tickets: list[dict[str, Any]], publish_ready: list[dict[str, Any]], editor_passed: list[dict[str, Any]]) -> dict[str, str]:
        if tickets:
            return {"label": "处理返工单", "kind": "rework"}
        if publish_ready:
            return {"label": "发布已确认正文", "kind": "publish"}
        if editor_passed:
            return {"label": "人工确认正文", "kind": "confirm"}
        if active:
            return {"label": f"继续第 {active.get('chapter_no')} 章", "kind": "active"}
        if candidates:
            return {"label": "推进候选章节", "kind": "candidate"}
        return {"label": "规划下一章", "kind": "plan"}
