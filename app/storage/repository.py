from __future__ import annotations

from typing import Any

from app.domain import Artifact, Book, ChapterPlan
from app.storage.database import Database


class Repository:
    def __init__(self, db: Database):
        self.db = db

    def _execute(self, conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
        return conn.cursor().execute(sql.replace("?", self.db.placeholder()), params)

    def _fetchone(self, conn: Any, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        cur = conn.cursor()
        cur.execute(sql.replace("?", self.db.placeholder()), params)
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def _fetchall(self, conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cur = conn.cursor()
        cur.execute(sql.replace("?", self.db.placeholder()), params)
        return [dict(row) for row in cur.fetchall()]

    def _last_id(self, cur: Any) -> int:
        return int(cur.lastrowid)

    def create_demo_book(self) -> int:
        existing = self.get_book_by_title("废校词条师")
        if existing:
            return existing.id
        with self.db.session() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO books (title, premise, status) VALUES (?, ?, ?)".replace("?", self.db.placeholder()),
                ("废校词条师", "一个被废校规则压住的少年，用词条改写命运，但每次改写都要付出代价。", "active"),
            )
            book_id = self._last_id(cur)
            self._seed_demo_architecture(conn, book_id)
            self.log_event(conn, book_id, None, "book_created", "demo book initialized")
            return book_id

    def _seed_demo_architecture(self, conn: Any, book_id: int) -> None:
        ph = self.db.placeholder()
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO volumes (book_id, title, goal, start_chapter, end_chapter) VALUES ({ph},{ph},{ph},{ph},{ph})",
            (book_id, "第一卷：废校开门", "主角拿到词条能力，但只能在规则压迫下小步试错。", 1, 50),
        )
        volume_id = self._last_id(cur)
        cur.execute(
            f"INSERT INTO story_arcs (book_id, volume_id, title, goal, pressure, start_chapter, end_chapter) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
            (book_id, volume_id, "入学验词", "三章内让主角保住入学资格，同时埋下废校真实门槛。", "排名、规则处罚、公开比较", 1, 3),
        )
        arc_id = self._last_id(cur)
        plans = [
            (1, "旧名单上的新生", "主角被点名为无效新生，必须当场证明词条有用。", "展示词条能改写一个小结果。", "不能揭露废校真正来历；不能解决入学危机。", "只兑现一个小胜，危机必须留到第3章。"),
            (2, "错字也是证据", "主角利用规则漏洞反咬考官，但代价暴露。", "揭示能力有副作用。", "不能让主角完全压过老师；不能公开核心秘密。", "允许打脸一次，但不能让关系从敌对跳到认可。"),
            (3, "第一条校规", "主角拿到临时资格，同时发现更大的规则债。", "兑现入学资格，埋下第一条校规伏笔。", "不能进入卷级终局；不能解释完整世界观。", "完成单元小高潮，但不能越级推进卷级问题。"),
        ]
        for chapter_no, title, objective, allowed, forbidden, pace in plans:
            cur.execute(
                f"""INSERT INTO chapter_plans
                    (book_id, volume_id, arc_id, chapter_no, title, objective, allowed_reveals, forbidden_reveals, pace_limit)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (book_id, volume_id, arc_id, chapter_no, title, objective, allowed, forbidden, pace),
            )
        cur.execute(
            f"INSERT INTO style_profiles (book_id, name, rules, locked) VALUES ({ph},{ph},{ph},{ph})",
            (book_id, "男频爽文-克制说明版", "短中长句自然混合；第一屏有可计量压力；设定通过行动、对话、代价露出；每章只解决当前层级问题。", 1),
        )
        cur.execute(
            f"INSERT INTO characters (book_id, name, role_type, desire, fear, voice) VALUES ({ph},{ph},{ph},{ph},{ph},{ph})",
            (book_id, "林砚", "protagonist", "保住入学资格并查清废校", "能力失控导致身边人受罚", "冷静、会算账，不喊口号"),
        )
        cur.execute(
            f"INSERT INTO foreshadowings (book_id, name, setup_chapter, payoff_window, note) VALUES ({ph},{ph},{ph},{ph},{ph})",
            (book_id, "第一条校规", 1, "3-8", "校规不能解释，只能以处罚和奖励体现。"),
        )
        cur.execute(
            f"INSERT INTO visibility_rules (book_id, secret, visible_after_chapter, note) VALUES ({ph},{ph},{ph},{ph})",
            (book_id, "废校真实来历", 50, "第一卷只给碎片，不允许说明书式展开。"),
        )
        cur.execute(
            f"INSERT INTO canon_facts (book_id, fact_type, content, status) VALUES ({ph},{ph},{ph},{ph})",
            (book_id, "world_rule", "词条可以改写局部结果，但代价必须落在当章或后续单元。", "official"),
        )

    def get_book_by_title(self, title: str) -> Book | None:
        with self.db.session() as conn:
            row = self._fetchone(conn, "SELECT id, title, premise, status FROM books WHERE title = ?", (title,))
        return Book(**row) if row else None

    def get_book(self, book_id: int) -> Book | None:
        with self.db.session() as conn:
            row = self._fetchone(conn, "SELECT id, title, premise, status FROM books WHERE id = ?", (book_id,))
        return Book(**row) if row else None

    def list_books(self) -> list[Book]:
        with self.db.session() as conn:
            rows = self._fetchall(conn, "SELECT id, title, premise, status FROM books ORDER BY id")
        return [Book(**row) for row in rows]

    def list_chapter_plans(self, book_id: int) -> list[ChapterPlan]:
        with self.db.session() as conn:
            rows = self._fetchall(conn, "SELECT * FROM chapter_plans WHERE book_id = ? ORDER BY chapter_no", (book_id,))
        return [ChapterPlan(**row) for row in rows]

    def get_chapter_plan(self, book_id: int, chapter_no: int) -> ChapterPlan | None:
        with self.db.session() as conn:
            row = self._fetchone(conn, "SELECT * FROM chapter_plans WHERE book_id = ? AND chapter_no = ?", (book_id, chapter_no))
        return ChapterPlan(**row) if row else None

    def get_architecture_context(self, book_id: int, chapter_no: int) -> dict[str, Any]:
        with self.db.session() as conn:
            plan = self._fetchone(conn, "SELECT * FROM chapter_plans WHERE book_id = ? AND chapter_no = ?", (book_id, chapter_no))
            if not plan:
                raise ValueError(f"chapter plan missing: book={book_id} chapter={chapter_no}")
            volume = self._fetchone(conn, "SELECT * FROM volumes WHERE id = ?", (plan["volume_id"],))
            arc = self._fetchone(conn, "SELECT * FROM story_arcs WHERE id = ?", (plan["arc_id"],))
            style = self._fetchone(conn, "SELECT * FROM style_profiles WHERE book_id = ? AND locked = 1 ORDER BY id LIMIT 1", (book_id,))
            characters = self._fetchall(conn, "SELECT * FROM characters WHERE book_id = ? ORDER BY id", (book_id,))
            foreshadowings = self._fetchall(conn, "SELECT * FROM foreshadowings WHERE book_id = ? ORDER BY id", (book_id,))
            visibility = self._fetchall(conn, "SELECT * FROM visibility_rules WHERE book_id = ? ORDER BY id", (book_id,))
            canon = self._fetchall(conn, "SELECT * FROM canon_facts WHERE book_id = ? ORDER BY id", (book_id,))
        return {"plan": plan, "volume": volume, "arc": arc, "style": style, "characters": characters, "foreshadowings": foreshadowings, "visibility": visibility, "canon": canon}

    def create_artifact(self, book_id: int, chapter_no: int | None, artifact_type: str, status: str, content: str, visibility: str = "internal") -> Artifact:
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(
                f"INSERT INTO artifacts (book_id, chapter_no, artifact_type, status, content, visibility) VALUES ({ph},{ph},{ph},{ph},{ph},{ph})",
                (book_id, chapter_no, artifact_type, status, content, visibility),
            )
            artifact_id = self._last_id(cur)
            self.log_event(conn, book_id, chapter_no, f"artifact_{artifact_type}", status)
        return Artifact(artifact_id, book_id, chapter_no, artifact_type, status, content)

    def latest_artifact(self, book_id: int, chapter_no: int, artifact_type: str) -> Artifact | None:
        with self.db.session() as conn:
            row = self._fetchone(
                conn,
                "SELECT * FROM artifacts WHERE book_id = ? AND chapter_no = ? AND artifact_type = ? ORDER BY id DESC LIMIT 1",
                (book_id, chapter_no, artifact_type),
            )
        return Artifact(row["id"], row["book_id"], row["chapter_no"], row["artifact_type"], row["status"], row["content"]) if row else None

    def get_artifact(self, artifact_id: int) -> Artifact | None:
        with self.db.session() as conn:
            row = self._fetchone(conn, "SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
        return Artifact(row["id"], row["book_id"], row["chapter_no"], row["artifact_type"], row["status"], row["content"]) if row else None

    def create_run(self, book_id: int, chapter_no: int) -> int:
        with self.db.session() as conn:
            cur = conn.cursor()
            ph = self.db.placeholder()
            cur.execute(f"INSERT INTO pipeline_runs (book_id, chapter_no, status) VALUES ({ph},{ph},{ph})", (book_id, chapter_no, "running"))
            run_id = self._last_id(cur)
            self.log_event(conn, book_id, chapter_no, "pipeline_started", f"run={run_id}")
            return run_id

    def finish_run(self, run_id: int, book_id: int, chapter_no: int, status: str) -> None:
        with self.db.session() as conn:
            self._execute(conn, "UPDATE pipeline_runs SET status = ? WHERE id = ?", (status, run_id))
            self.log_event(conn, book_id, chapter_no, "pipeline_finished", status)

    def save_chapter_body(self, book_id: int, chapter_no: int, title: str, body: str) -> None:
        with self.db.session() as conn:
            ph = self.db.placeholder()
            if self.db.is_mysql:
                sql = f"""INSERT INTO chapter_bodies (book_id, chapter_no, title, body, status)
                    VALUES ({ph},{ph},{ph},{ph},{ph})
                    ON DUPLICATE KEY UPDATE title=VALUES(title), body=VALUES(body), status=VALUES(status)"""
            else:
                sql = f"""INSERT INTO chapter_bodies (book_id, chapter_no, title, body, status)
                    VALUES ({ph},{ph},{ph},{ph},{ph})
                    ON CONFLICT(book_id, chapter_no) DO UPDATE SET title=excluded.title, body=excluded.body, status=excluded.status"""
            conn.cursor().execute(sql, (book_id, chapter_no, title, body, "approved"))
            self.log_event(conn, book_id, chapter_no, "chapter_body_saved", "approved")

    def get_chapter_body(self, book_id: int, chapter_no: int) -> dict[str, Any] | None:
        with self.db.session() as conn:
            return self._fetchone(conn, "SELECT * FROM chapter_bodies WHERE book_id = ? AND chapter_no = ?", (book_id, chapter_no))

    def list_events(self, book_id: int, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            return self._fetchall(conn, "SELECT * FROM events WHERE book_id = ? ORDER BY id DESC LIMIT ?", (book_id, limit))

    def log_event(self, conn: Any, book_id: int, chapter_no: int | None, event_type: str, message: str) -> None:
        ph = self.db.placeholder()
        conn.cursor().execute(f"INSERT INTO events (book_id, chapter_no, event_type, message) VALUES ({ph},{ph},{ph},{ph})", (book_id, chapter_no, event_type, message))

    def dashboard(self) -> dict[str, Any]:
        books = self.list_books()
        if not books:
            return {"books": [], "current": None, "plans": [], "events": []}
        current = books[0]
        return {"books": books, "current": current, "plans": self.list_chapter_plans(current.id), "events": self.list_events(current.id)}
