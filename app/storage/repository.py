from __future__ import annotations

import json
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
}

DEFAULT_AUTHOR = {
    "name": "默认商业男频作者",
    "genre": "中国网文男频爽文",
    "pov_preference": "third_limited",
    "sentence_rhythm": "短句、中句、少量长句自然混合；动作句推动，心理句收束。",
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
        target_chars_min: int = 2200,
        target_chars_max: int = 3200,
        story_mainline: str = "",
        worldbuilding: str = "",
        imported_outline: str = "",
        characters_text: str = "",
    ) -> int:
        title = title.strip() or "未命名作品"
        if self.get_book_by_title(title, statuses=("active",)):
            raise ValueError("同名正式作品已存在，请改名或先归档旧作品。")
        premise = premise.strip() or "请补充作品核心卖点。"
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
                 story_mainline, worldbuilding, imported_outline, author_profile_id, editor_profile_id, book_author_profile_id, book_editor_profile_id)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (
                    title,
                    premise,
                    "active",
                    genre.strip(),
                    market_channel.strip(),
                    target_reader.strip(),
                    pov_policy.strip() or "third_limited",
                    int(target_chars_min),
                    int(target_chars_max),
                    story_mainline.strip(),
                    worldbuilding.strip(),
                    imported_outline.strip(),
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
            self.log_event(conn, book_id, None, "book_created", "正式作品已创建并生成开书基础设定")
            return book_id

    def _seed_architecture(self, conn: Any, book_id: int) -> None:
        book = self._fetchone(conn, "SELECT * FROM books WHERE id = ?", (book_id,))
        ph = self.db.placeholder()
        cur = conn.cursor()
        mainline = book.get("story_mainline") or "主角在持续升级的压力中夺回解释权，并以代价换取阶段胜利。"
        volume_goal = f"第一卷建立主角困境、能力代价和第一阶段对手；全书主线：{mainline}"
        cur.execute(
            f"INSERT INTO volumes (book_id, title, goal, start_chapter, end_chapter) VALUES ({ph},{ph},{ph},{ph},{ph})",
            (book_id, "第一卷：起势", volume_goal, 1, 50),
        )
        volume_id = self._last_id(cur)
        cur.execute(
            f"INSERT INTO story_arcs (book_id, volume_id, title, goal, pressure, start_chapter, end_chapter) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
            (book_id, volume_id, "前三章小单元", "完成一次压迫、反击、代价落点的小闭环。", "排名、资源、规则、公开比较轮换", 1, 3),
        )
        arc_id = self._last_id(cur)
        plans = [
            (1, "开局压迫", "首屏给出可计量压力，主角必须行动。", "露出核心能力的一个小用法。", "不能解释完整世界观；不能解决单元危机。", "只允许小胜，留下反噬或代价。"),
            (2, "反咬一口", "用第一章细节打回去，同时暴露新限制。", "揭示能力代价或对手漏洞。", "不能让关系跳级；不能让主角无成本碾压。", "允许打脸一次，但不能提前完成单元高潮。"),
            (3, "小高潮兑现", "兑现当前单元目标，同时打开下一单元问题。", "兑现本单元爽点。", "不能进入卷级终局；不能说明书式展开设定。", "完成单元闭环，但不能越级推进卷级问题。"),
        ]
        for no, title, objective, allowed, forbidden, pace in plans:
            cur.execute(
                f"""INSERT INTO chapter_plans
                (book_id, volume_id, arc_id, chapter_no, title, objective, allowed_reveals, forbidden_reveals, pace_limit, plot_summary, target_chars)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (book_id, volume_id, arc_id, no, title, objective, allowed, forbidden, pace, objective, 2600),
            )
        self._insert_default_controls(conn, book_id)

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
                (book_id, "主角", "protagonist", "在规则压迫中夺回主动权", "胜利代价反噬自身或同伴", "冷静、有判断，不喊口号", "开书时由 AI 预生成，待作者补充小传。"),
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
                book.get("market_channel") or "中国网文男频爽文",
                int(book.get("target_chars_min") or 2200),
                int(book.get("target_chars_max") or 3200),
                3,
                book.get("pov_policy") or "third_limited",
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
            (
                book_id,
                profile_id,
                profile["name"],
                profile["genre"],
                profile["pov_preference"],
                profile["sentence_rhythm"],
                profile["dialogue_style"],
                profile["payoff_preference"],
                profile["forbidden_items"],
                profile["prompt_rules"],
                "",
            ),
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
            (
                book_id,
                profile_id,
                profile["name"],
                profile["platform"],
                profile["word_count_rule"],
                profile["pov_rule"],
                profile["structure_rule"],
                profile["payoff_rule"],
                profile["pollution_rule"],
                int(profile["reject_threshold"]),
            ),
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

    def update_book_setup(self, book_id: int, data: dict[str, Any]) -> None:
        allowed = ["title", "premise", "genre", "market_channel", "target_reader", "pov_policy", "target_chars_min", "target_chars_max", "story_mainline", "worldbuilding", "imported_outline"]
        values = {key: data.get(key, "") for key in allowed}
        values["target_chars_min"] = int(values["target_chars_min"] or 2200)
        values["target_chars_max"] = int(values["target_chars_max"] or 3200)
        with self.db.session() as conn:
            assigns = ", ".join([f"{key} = ?" for key in allowed])
            self._execute(conn, f"UPDATE books SET {assigns} WHERE id = ?", (*values.values(), book_id))
            self.update_style_and_settings(
                book_id,
                self.get_book_controls(book_id)["style"]["rules"],
                values["market_channel"],
                values["target_chars_min"],
                values["target_chars_max"],
                3,
                values["pov_policy"],
                "每章至少有一个可感知压力源和一个可兑现的小爽点。",
                "章节服务单元，单元服务卷；不越级推进。",
            )
            self.log_event(conn, book_id, None, "book_setup_updated", "开书设定已更新")

    def update_book(self, book_id: int, title: str, premise: str) -> None:
        self.update_book_setup(book_id, {"title": title, "premise": premise, **(self.get_book_record(book_id) or {})})

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
        tables = ["volumes", "story_arcs", "chapter_batches", "chapter_plans", "style_profiles", "production_settings", "book_author_profiles", "book_editor_profiles", "characters", "relationships", "foreshadowings", "canon_facts", "visibility_rules", "artifacts", "chapter_bodies", "pipeline_runs", "rewrite_tasks", "continuity_memories", "continuity_atoms", "memory_retrieval_logs", "drift_reports", "export_records", "events"]
        with self.db.session() as conn:
            for table in tables:
                self._execute(conn, f"DELETE FROM {table} WHERE book_id = ?", (book_id,))
            self._execute(conn, "DELETE FROM books WHERE id = ?", (book_id,))

    def update_cover(self, book_id: int, cover_path: str) -> None:
        with self.db.session() as conn:
            self._execute(conn, "UPDATE books SET cover_path = ? WHERE id = ?", (cover_path, book_id))
            self.log_event(conn, book_id, None, "cover_updated", "封面已更新")

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

    def update_style_and_settings(self, book_id: int, style_rules: str, market_channel: str, target_chars_min: int, target_chars_max: int, chapter_unit_size: int, pov_policy: str, hook_policy: str, pacing_policy: str) -> None:
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
            conn.cursor().execute(sql, (book_id, market_channel.strip(), int(target_chars_min), int(target_chars_max), int(chapter_unit_size), pov_policy.strip(), hook_policy.strip(), pacing_policy.strip()))

    def update_architecture(self, book_id: int, volume_title: str, volume_goal: str, arc_title: str, arc_goal: str, arc_pressure: str) -> None:
        with self.db.session() as conn:
            volume = self._fetchone(conn, "SELECT * FROM volumes WHERE book_id = ? ORDER BY start_chapter LIMIT 1", (book_id,))
            arc = self._fetchone(conn, "SELECT * FROM story_arcs WHERE book_id = ? ORDER BY start_chapter LIMIT 1", (book_id,))
            if volume:
                self._execute(conn, "UPDATE volumes SET title = ?, goal = ? WHERE id = ?", (volume_title.strip(), volume_goal.strip(), volume["id"]))
            if arc:
                self._execute(conn, "UPDATE story_arcs SET title = ?, goal = ?, pressure = ? WHERE id = ?", (arc_title.strip(), arc_goal.strip(), arc_pressure.strip(), arc["id"]))
            self.log_event(conn, book_id, None, "architecture_updated", "大纲已更新")

    def list_chapter_plans(self, book_id: int) -> list[ChapterPlan]:
        with self.db.session() as conn:
            rows = self._fetchall(conn, "SELECT * FROM chapter_plans WHERE book_id = ? ORDER BY chapter_no", (book_id,))
        return [ChapterPlan(**{key: row[key] for key in ChapterPlan.__dataclass_fields__ if key in row}) for row in rows]

    def list_chapter_plan_rows(self, book_id: int, batch_id: int | None = None) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            if batch_id:
                return self._fetchall(conn, "SELECT * FROM chapter_plans WHERE book_id = ? AND batch_id = ? ORDER BY chapter_no", (book_id, batch_id))
            return self._fetchall(conn, "SELECT * FROM chapter_plans WHERE book_id = ? ORDER BY chapter_no", (book_id,))

    def get_chapter_plan(self, book_id: int, chapter_no: int) -> ChapterPlan | None:
        with self.db.session() as conn:
            row = self._fetchone(conn, "SELECT * FROM chapter_plans WHERE book_id = ? AND chapter_no = ?", (book_id, chapter_no))
        return ChapterPlan(**{key: row[key] for key in ChapterPlan.__dataclass_fields__ if key in row}) if row else None

    def get_chapter_plan_row(self, book_id: int, chapter_no: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT * FROM chapter_plans WHERE book_id = ? AND chapter_no = ?", (book_id, chapter_no))

    def update_chapter_plan(self, book_id: int, chapter_no: int, title: str, objective: str, allowed_reveals: str, forbidden_reveals: str, pace_limit: str, plot_summary: str = "", target_chars: int = 2600) -> None:
        with self.db.session() as conn:
            self._execute(conn, """UPDATE chapter_plans SET title = ?, objective = ?, allowed_reveals = ?, forbidden_reveals = ?, pace_limit = ?, plot_summary = ?, target_chars = ? WHERE book_id = ? AND chapter_no = ?""", (title.strip(), objective.strip(), allowed_reveals.strip(), forbidden_reveals.strip(), pace_limit.strip(), plot_summary.strip(), int(target_chars), book_id, chapter_no))
            self.log_event(conn, book_id, chapter_no, "chapter_plan_updated", "章节卡片已保存")

    def create_chapter_batch(self, book_id: int, chapter_count: int) -> int:
        count = max(1, min(20, int(chapter_count or 3)))
        controls = self.get_book_controls(book_id)
        with self.db.session() as conn:
            last = self._fetchone(conn, "SELECT MAX(chapter_no) AS chapter_no FROM chapter_plans WHERE book_id = ?", (book_id,))
            start = int(last["chapter_no"] or 0) + 1
            end = start + count - 1
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(f"INSERT INTO chapter_batches (book_id, start_chapter, end_chapter, chapter_count, status, progress_message) VALUES ({ph},{ph},{ph},{ph},{ph},{ph})", (book_id, start, end, count, "planning", "章节卡片已生成，等待作者确认。"))
            batch_id = self._last_id(cur)
            volume = controls["volume"]
            arc = controls["arc"]
            for no in range(start, end + 1):
                title = f"第{no}章 待命名"
                objective = f"承接第{no - 1}章结果，推进当前单元目标并留下下一章钩子。"
                cur.execute(
                    f"""INSERT INTO chapter_plans
                    (book_id, volume_id, arc_id, batch_id, chapter_no, title, objective, allowed_reveals, forbidden_reveals, pace_limit, plot_summary, target_chars)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                    (book_id, volume["id"], arc["id"], batch_id, no, title, objective, "只揭示本章角色可见信息。", "不能越级解释世界观或卷级终局。", "服务当前单元，不越级推进。", objective, 2600),
                )
            self._execute(conn, "UPDATE books SET current_chapter_no = ? WHERE id = ?", (end, book_id))
            self.log_event(conn, book_id, None, "chapter_batch_created", f"已创建第 {start}-{end} 章卡片")
            return batch_id

    def get_chapter_batch(self, batch_id: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT * FROM chapter_batches WHERE id = ?", (batch_id,))

    def list_chapter_batches(self, book_id: int) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            return self._fetchall(conn, "SELECT * FROM chapter_batches WHERE book_id = ? ORDER BY id DESC", (book_id,))

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

    def update_book_author_profile(self, book_id: int, data: dict[str, Any]) -> None:
        fields = ["name", "genre", "pov_preference", "sentence_rhythm", "dialogue_style", "payoff_preference", "forbidden_items", "prompt_rules", "sample_summary"]
        controls = self.get_book_controls(book_id)
        profile_id = controls["book"]["book_author_profile_id"]
        with self.db.session() as conn:
            assigns = ",".join([f"{field} = ?" for field in fields])
            self._execute(conn, f"UPDATE book_author_profiles SET {assigns} WHERE id = ?", (*(data.get(field, "") for field in fields), profile_id))

    def update_book_editor_profile(self, book_id: int, data: dict[str, Any]) -> None:
        fields = ["name", "platform", "word_count_rule", "pov_rule", "structure_rule", "payoff_rule", "pollution_rule", "reject_threshold"]
        controls = self.get_book_controls(book_id)
        profile_id = controls["book"]["book_editor_profile_id"]
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

    def finish_run(self, run_id: int, book_id: int, chapter_no: int, status: str) -> None:
        with self.db.session() as conn:
            self._execute(conn, "UPDATE pipeline_runs SET status = ? WHERE id = ?", (status, run_id))
            self.log_event(conn, book_id, chapter_no, "生成结束", status)

    def create_rewrite_task(self, book_id: int, chapter_no: int, review_artifact_id: int, error: str = "") -> dict[str, Any]:
        with self.db.session() as conn:
            existing = self._fetchone(conn, "SELECT * FROM rewrite_tasks WHERE book_id = ? AND chapter_no = ? AND status IN ('pending','running') ORDER BY id DESC LIMIT 1", (book_id, chapter_no))
            if existing:
                return existing
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

    def list_exports(self, book_id: int | None = None) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            if book_id:
                return self._fetchall(conn, "SELECT * FROM export_records WHERE book_id = ? ORDER BY id DESC", (book_id,))
            return self._fetchall(conn, "SELECT e.*, b.title AS book_title FROM export_records e LEFT JOIN books b ON b.id = e.book_id ORDER BY e.id DESC")

    def create_memory(self, book_id: int, memory_type: str, scope_key: str, content: dict[str, Any] | str, start: int | None = None, end: int | None = None, source_export_id: int | None = None, token_budget: int = 1200) -> dict[str, Any]:
        text = json.dumps(content, ensure_ascii=False, indent=2) if not isinstance(content, str) else content
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
            cur.execute(f"INSERT INTO drift_reports (book_id, chapter_no, content) VALUES ({ph},{ph},{ph})", (book_id, chapter_no, json.dumps(content, ensure_ascii=False, indent=2)))
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
