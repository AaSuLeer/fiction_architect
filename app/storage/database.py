from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from app.config import Settings


SCHEMA_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        title VARCHAR(255) NOT NULL,
        premise TEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS volumes (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        title VARCHAR(255) NOT NULL,
        goal TEXT NOT NULL,
        start_chapter INTEGER NOT NULL,
        end_chapter INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS story_arcs (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        volume_id INTEGER NOT NULL,
        title VARCHAR(255) NOT NULL,
        goal TEXT NOT NULL,
        pressure TEXT NOT NULL,
        start_chapter INTEGER NOT NULL,
        end_chapter INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chapter_plans (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        volume_id INTEGER NOT NULL,
        arc_id INTEGER NOT NULL,
        chapter_no INTEGER NOT NULL,
        title VARCHAR(255) NOT NULL,
        objective TEXT NOT NULL,
        allowed_reveals TEXT NOT NULL,
        forbidden_reveals TEXT NOT NULL,
        pace_limit TEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'planned',
        UNIQUE (book_id, chapter_no)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS style_profiles (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        name VARCHAR(255) NOT NULL,
        rules TEXT NOT NULL,
        locked INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS production_settings (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        market_channel VARCHAR(100) NOT NULL DEFAULT '男频爽文',
        target_chars_min INTEGER NOT NULL DEFAULT 1800,
        target_chars_max INTEGER NOT NULL DEFAULT 2600,
        chapter_unit_size INTEGER NOT NULL DEFAULT 3,
        pov_policy VARCHAR(100) NOT NULL DEFAULT 'third_limited',
        hook_policy TEXT NOT NULL,
        pacing_policy TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (book_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS characters (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        name VARCHAR(255) NOT NULL,
        role_type VARCHAR(100) NOT NULL,
        desire TEXT NOT NULL,
        fear TEXT NOT NULL,
        voice TEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'active'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS relationships (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        character_a VARCHAR(255) NOT NULL,
        character_b VARCHAR(255) NOT NULL,
        state TEXT NOT NULL,
        forbidden_jump TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS foreshadowings (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        name VARCHAR(255) NOT NULL,
        setup_chapter INTEGER NOT NULL,
        payoff_window VARCHAR(100) NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'open',
        note TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canon_facts (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        fact_type VARCHAR(100) NOT NULL,
        content TEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'official'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visibility_rules (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        secret TEXT NOT NULL,
        visible_after_chapter INTEGER NOT NULL,
        note TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS artifacts (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER,
        artifact_type VARCHAR(100) NOT NULL,
        status VARCHAR(50) NOT NULL,
        content TEXT NOT NULL,
        visibility VARCHAR(50) NOT NULL DEFAULT 'internal',
        expires_at TIMESTAMP NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chapter_bodies (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER NOT NULL,
        title VARCHAR(255) NOT NULL,
        body TEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'approved',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (book_id, chapter_no)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER NOT NULL,
        status VARCHAR(50) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER,
        event_type VARCHAR(100) NOT NULL,
        message TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
]


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def is_mysql(self) -> bool:
        return self.settings.using_mysql

    def _connect_mysql(self) -> Any:
        try:
            import pymysql
        except ImportError as exc:
            raise RuntimeError("MySQL mode requires pymysql. Install requirements.txt first.") from exc
        return pymysql.connect(
            host=self.settings.mysql_host,
            port=self.settings.mysql_port,
            user=self.settings.mysql_user,
            password=self.settings.mysql_password,
            database=self.settings.mysql_database,
            charset="utf8mb4",
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def create_mysql_database_if_needed(self) -> None:
        if not self.settings.using_mysql:
            return
        try:
            import pymysql
        except ImportError as exc:
            raise RuntimeError("MySQL mode requires pymysql. Install requirements.txt first.") from exc
        db_name = self.settings.mysql_database
        if not db_name.replace("_", "").isalnum():
            raise RuntimeError("MYSQL_DATABASE may only contain letters, numbers, and underscores.")
        conn = pymysql.connect(
            host=self.settings.mysql_host,
            port=self.settings.mysql_port,
            user=self.settings.mysql_user,
            password=self.settings.mysql_password,
            charset="utf8mb4",
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            conn.cursor().execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        finally:
            conn.close()

    def connect(self) -> Any:
        if self.settings.using_mysql:
            return self._connect_mysql()
        self.settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.settings.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def session(self) -> Iterator[Any]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def placeholder(self) -> str:
        return "%s" if self.settings.using_mysql else "?"

    def adapt_sql(self, sql: str) -> str:
        if self.settings.using_mysql:
            return sql
        return sql.replace(" INTEGER PRIMARY KEY AUTO_INCREMENT", " INTEGER PRIMARY KEY AUTOINCREMENT")


def initialize_database(db: Database) -> None:
    db.create_mysql_database_if_needed()
    with db.session() as conn:
        cur = conn.cursor()
        for statement in SCHEMA_TABLES:
            cur.execute(db.adapt_sql(statement))
        _ensure_schema_columns(db, conn)


def _ensure_schema_columns(db: Database, conn: Any) -> None:
    if db.settings.using_mysql:
        cur = conn.cursor()
        cur.execute("SHOW COLUMNS FROM production_settings LIKE 'pov_policy'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE production_settings ADD COLUMN pov_policy VARCHAR(100) NOT NULL DEFAULT 'third_limited'")
        return
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(production_settings)")
    columns = {row[1] for row in cur.fetchall()}
    if "pov_policy" not in columns:
        cur.execute("ALTER TABLE production_settings ADD COLUMN pov_policy VARCHAR(100) NOT NULL DEFAULT 'third_limited'")
