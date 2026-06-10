from __future__ import annotations

import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.config import Settings


SCHEMA_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        title VARCHAR(255) NOT NULL,
        premise TEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'active',
        cover_path TEXT,
        genre VARCHAR(100) NOT NULL DEFAULT '',
        market_channel VARCHAR(100) NOT NULL DEFAULT '中国网文男频爽文',
        target_reader TEXT NOT NULL DEFAULT '',
        pov_policy VARCHAR(100) NOT NULL DEFAULT 'third_limited',
        target_chars_min INTEGER NOT NULL DEFAULT 2200,
        target_chars_max INTEGER NOT NULL DEFAULT 3200,
        story_mainline TEXT NOT NULL DEFAULT '',
        worldbuilding TEXT NOT NULL DEFAULT '',
        imported_outline TEXT NOT NULL DEFAULT '',
        book_outline TEXT NOT NULL DEFAULT '',
        estimated_total_words INTEGER NOT NULL DEFAULT 1000000,
        outline_locked INTEGER NOT NULL DEFAULT 0,
        outline_confirmed_at TIMESTAMP NULL,
        current_chapter_no INTEGER NOT NULL DEFAULT 0,
        author_profile_id INTEGER,
        editor_profile_id INTEGER,
        book_author_profile_id INTEGER,
        book_editor_profile_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS volumes (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        title VARCHAR(255) NOT NULL,
        goal TEXT NOT NULL,
        estimated_words INTEGER NOT NULL DEFAULT 200000,
        core_conflict TEXT NOT NULL DEFAULT '',
        stage_payoff TEXT NOT NULL DEFAULT '',
        character_progression TEXT NOT NULL DEFAULT '',
        foreshadowing_plan TEXT NOT NULL DEFAULT '',
        manual_edited INTEGER NOT NULL DEFAULT 0,
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
        cause TEXT NOT NULL DEFAULT '',
        process TEXT NOT NULL DEFAULT '',
        result TEXT NOT NULL DEFAULT '',
        payoff TEXT NOT NULL DEFAULT '',
        character_change TEXT NOT NULL DEFAULT '',
        foreshadowing_progress TEXT NOT NULL DEFAULT '',
        recommended_chapters INTEGER NOT NULL DEFAULT 5,
        status VARCHAR(50) NOT NULL DEFAULT 'planned',
        manual_edited INTEGER NOT NULL DEFAULT 0,
        start_chapter INTEGER NOT NULL,
        end_chapter INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chapter_batches (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        volume_id INTEGER,
        arc_id INTEGER,
        start_chapter INTEGER NOT NULL,
        end_chapter INTEGER NOT NULL,
        chapter_count INTEGER NOT NULL,
        recommended_count INTEGER NOT NULL DEFAULT 5,
        author_count INTEGER NOT NULL DEFAULT 5,
        status VARCHAR(50) NOT NULL DEFAULT 'planning',
        progress_message TEXT NOT NULL DEFAULT '',
        error TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chapter_candidates (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        volume_id INTEGER,
        arc_id INTEGER,
        chapter_no INTEGER NOT NULL,
        title VARCHAR(255) NOT NULL,
        work_order LONGTEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'candidate',
        validation_errors LONGTEXT NOT NULL DEFAULT '',
        source VARCHAR(50) NOT NULL DEFAULT 'planner',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (book_id, chapter_no)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chapter_plans (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        volume_id INTEGER NOT NULL,
        arc_id INTEGER NOT NULL,
        batch_id INTEGER,
        chapter_no INTEGER NOT NULL,
        title VARCHAR(255) NOT NULL,
        objective TEXT NOT NULL,
        allowed_reveals TEXT NOT NULL,
        forbidden_reveals TEXT NOT NULL,
        pace_limit TEXT NOT NULL,
        plot_summary TEXT NOT NULL DEFAULT '',
        target_chars INTEGER NOT NULL DEFAULT 2600,
        review_rounds INTEGER NOT NULL DEFAULT 0,
        unique_task TEXT NOT NULL DEFAULT '',
        core_event TEXT NOT NULL DEFAULT '',
        tech_progression TEXT NOT NULL DEFAULT '',
        character_roles TEXT NOT NULL DEFAULT '',
        antagonist_move TEXT NOT NULL DEFAULT '',
        external_pressure TEXT NOT NULL DEFAULT '',
        irreversible_change TEXT NOT NULL DEFAULT '',
        ending_hook TEXT NOT NULL DEFAULT '',
        no_repeat_guard TEXT NOT NULL DEFAULT '',
        manual_edited INTEGER NOT NULL DEFAULT 0,
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
        market_channel VARCHAR(100) NOT NULL DEFAULT '中国网文男频爽文',
        target_chars_min INTEGER NOT NULL DEFAULT 2200,
        target_chars_max INTEGER NOT NULL DEFAULT 3200,
        chapter_unit_size INTEGER NOT NULL DEFAULT 3,
        pov_policy VARCHAR(100) NOT NULL DEFAULT 'third_limited',
        hook_policy TEXT NOT NULL,
        pacing_policy TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (book_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS author_profiles (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        name VARCHAR(255) NOT NULL UNIQUE,
        genre TEXT NOT NULL,
        pov_preference VARCHAR(100) NOT NULL DEFAULT 'third_limited',
        sentence_rhythm TEXT NOT NULL,
        dialogue_style TEXT NOT NULL,
        payoff_preference TEXT NOT NULL,
        forbidden_items TEXT NOT NULL,
        prompt_rules TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS editor_profiles (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        name VARCHAR(255) NOT NULL UNIQUE,
        platform VARCHAR(255) NOT NULL,
        word_count_rule TEXT NOT NULL,
        pov_rule TEXT NOT NULL,
        structure_rule TEXT NOT NULL,
        payoff_rule TEXT NOT NULL,
        pollution_rule TEXT NOT NULL,
        reject_threshold INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS book_author_profiles (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        source_profile_id INTEGER,
        name VARCHAR(255) NOT NULL,
        genre TEXT NOT NULL,
        pov_preference VARCHAR(100) NOT NULL DEFAULT 'third_limited',
        sentence_rhythm TEXT NOT NULL,
        dialogue_style TEXT NOT NULL,
        payoff_preference TEXT NOT NULL,
        forbidden_items TEXT NOT NULL,
        prompt_rules TEXT NOT NULL,
        sample_summary TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS book_editor_profiles (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        source_profile_id INTEGER,
        name VARCHAR(255) NOT NULL,
        platform VARCHAR(255) NOT NULL,
        word_count_rule TEXT NOT NULL,
        pov_rule TEXT NOT NULL,
        structure_rule TEXT NOT NULL,
        payoff_rule TEXT NOT NULL,
        pollution_rule TEXT NOT NULL,
        reject_threshold INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        biography TEXT NOT NULL DEFAULT '',
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
        content LONGTEXT NOT NULL,
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
        body LONGTEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'drafted',
        export_id INTEGER,
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
        error TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chapter_tasks (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'task_ready',
        opening_state LONGTEXT NOT NULL,
        mission LONGTEXT NOT NULL,
        definition_of_done LONGTEXT NOT NULL,
        scene_route LONGTEXT NOT NULL,
        irreversible_change LONGTEXT NOT NULL,
        handoff_to_next LONGTEXT NOT NULL,
        forbidden_future LONGTEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1,
        source_plan_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chapter_state_snapshots (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER NOT NULL,
        status VARCHAR(50) NOT NULL,
        opening_state LONGTEXT NOT NULL,
        closing_state LONGTEXT NOT NULL,
        unit_state LONGTEXT NOT NULL,
        style_signature LONGTEXT NOT NULL,
        source_export_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chapter_transitions (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER NOT NULL,
        from_state LONGTEXT NOT NULL,
        to_state LONGTEXT NOT NULL,
        transition_summary LONGTEXT NOT NULL,
        source_export_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS editorial_decisions (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER NOT NULL,
        run_id INTEGER,
        review_artifact_id INTEGER,
        draft_id INTEGER,
        decision VARCHAR(50) NOT NULL,
        score INTEGER NOT NULL DEFAULT 0,
        failure_code VARCHAR(100) NOT NULL DEFAULT '',
        route VARCHAR(50) NOT NULL DEFAULT '',
        evidence LONGTEXT NOT NULL,
        required_fixes LONGTEXT NOT NULL,
        retryable INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS model_call_logs (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER,
        chapter_no INTEGER,
        run_id INTEGER,
        role VARCHAR(50) NOT NULL,
        model VARCHAR(255) NOT NULL,
        status VARCHAR(50) NOT NULL,
        elapsed_ms INTEGER NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS production_runs (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER NOT NULL,
        run_type VARCHAR(50) NOT NULL DEFAULT 'chapter',
        status VARCHAR(50) NOT NULL,
        failure_code VARCHAR(100) NOT NULL DEFAULT '',
        error TEXT NOT NULL DEFAULT '',
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        finished_at TIMESTAMP NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_runs (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER,
        flow_name VARCHAR(100) NOT NULL,
        state VARCHAR(50) NOT NULL,
        current_step VARCHAR(100) NOT NULL DEFAULT '',
        progress INTEGER NOT NULL DEFAULT 0,
        error LONGTEXT NOT NULL DEFAULT '',
        payload LONGTEXT NOT NULL DEFAULT '',
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        finished_at TIMESTAMP NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_events (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        run_id INTEGER,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER,
        event_type VARCHAR(100) NOT NULL,
        message TEXT NOT NULL,
        payload LONGTEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS construction_packets (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER NOT NULL,
        run_id INTEGER,
        content LONGTEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chapter_drafts (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER NOT NULL,
        run_id INTEGER,
        source_packet_id INTEGER,
        rewrite_of_draft_id INTEGER,
        status VARCHAR(50) NOT NULL DEFAULT 'drafted',
        content LONGTEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rework_tickets (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER NOT NULL,
        run_id INTEGER,
        editorial_decision_id INTEGER NOT NULL,
        route VARCHAR(50) NOT NULL DEFAULT 'writer',
        failure_code VARCHAR(100) NOT NULL DEFAULT '',
        required_fixes LONGTEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'open',
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 2,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS human_approval_logs (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER NOT NULL,
        decision VARCHAR(50) NOT NULL,
        body_hash VARCHAR(128) NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS official_canon (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER,
        canon_type VARCHAR(100) NOT NULL,
        content LONGTEXT NOT NULL,
        source_export_id INTEGER,
        source_event_id INTEGER,
        source_snapshot_id INTEGER,
        supersedes_canon_id INTEGER,
        version INTEGER NOT NULL DEFAULT 1,
        status VARCHAR(50) NOT NULL DEFAULT 'published',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonized_events (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER,
        event_type VARCHAR(100) NOT NULL,
        source_export_id INTEGER,
        content LONGTEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ledger_update_candidates (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER,
        ledger_type VARCHAR(100) NOT NULL,
        subject_key VARCHAR(255) NOT NULL DEFAULT '',
        content LONGTEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'candidate',
        source_export_id INTEGER,
        source_snapshot_id INTEGER,
        supersedes_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS character_states (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        character_key VARCHAR(255) NOT NULL,
        chapter_no INTEGER,
        state LONGTEXT NOT NULL,
        source_snapshot_id INTEGER,
        supersedes_id INTEGER,
        status VARCHAR(50) NOT NULL DEFAULT 'published',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS relationship_states (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        subject_key VARCHAR(255) NOT NULL,
        chapter_no INTEGER,
        state LONGTEXT NOT NULL,
        source_snapshot_id INTEGER,
        supersedes_id INTEGER,
        status VARCHAR(50) NOT NULL DEFAULT 'published',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS foreshadowing_ledger (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        thread_key VARCHAR(255) NOT NULL,
        chapter_no INTEGER,
        ledger_status VARCHAR(50) NOT NULL DEFAULT 'open',
        content LONGTEXT NOT NULL,
        source_snapshot_id INTEGER,
        supersedes_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS setting_ledger (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        subject_key VARCHAR(255) NOT NULL,
        chapter_no INTEGER,
        content LONGTEXT NOT NULL,
        source_snapshot_id INTEGER,
        supersedes_id INTEGER,
        status VARCHAR(50) NOT NULL DEFAULT 'published',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS progression_ledger (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        subject_key VARCHAR(255) NOT NULL,
        chapter_no INTEGER,
        content LONGTEXT NOT NULL,
        source_snapshot_id INTEGER,
        supersedes_id INTEGER,
        status VARCHAR(50) NOT NULL DEFAULT 'published',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rewrite_tasks (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER NOT NULL,
        review_artifact_id INTEGER NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        error TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS continuity_memories (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        memory_type VARCHAR(50) NOT NULL,
        scope_key VARCHAR(100) NOT NULL,
        version INTEGER NOT NULL,
        source_export_id INTEGER,
        source_start_chapter INTEGER,
        source_end_chapter INTEGER,
        is_current INTEGER NOT NULL DEFAULT 1,
        compression_mode VARCHAR(50) NOT NULL DEFAULT 'structured_budget',
        token_budget INTEGER NOT NULL DEFAULT 1200,
        retrieval_count INTEGER NOT NULL DEFAULT 0,
        last_used_at TIMESTAMP NULL,
        content LONGTEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS continuity_atoms (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER,
        atom_type VARCHAR(100) NOT NULL,
        content LONGTEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'candidate',
        visible_after_chapter INTEGER NOT NULL DEFAULT 0,
        source_ref VARCHAR(100) NOT NULL,
        source_export_id INTEGER,
        characters TEXT NOT NULL DEFAULT '',
        foreshadowing_tags TEXT NOT NULL DEFAULT '',
        confidence REAL NOT NULL DEFAULT 0.6,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_retrieval_logs (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        run_id INTEGER,
        chapter_no INTEGER NOT NULL,
        query TEXT NOT NULL,
        selected_memory_ids TEXT NOT NULL,
        selected_atom_ids TEXT NOT NULL,
        reason TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS drift_reports (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        chapter_no INTEGER,
        status VARCHAR(50) NOT NULL DEFAULT 'open',
        content LONGTEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS export_records (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        export_type VARCHAR(50) NOT NULL,
        file_path TEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'ready',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS export_versions (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        book_id INTEGER NOT NULL,
        export_id INTEGER NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        status VARCHAR(50) NOT NULL DEFAULT 'created',
        body_hash VARCHAR(128) NOT NULL DEFAULT '',
        source_chapters TEXT NOT NULL DEFAULT '',
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
        try:
            conn = sqlite3.connect(self.settings.sqlite_path)
        except sqlite3.OperationalError:
            fallback = Path(tempfile.gettempdir()) / "fiction_architect" / self.settings.sqlite_path.name
            fallback.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(fallback)
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
            return sql.replace("TEXT NOT NULL DEFAULT ''", "TEXT NULL")
        return sql.replace(" INTEGER PRIMARY KEY AUTO_INCREMENT", " INTEGER PRIMARY KEY AUTOINCREMENT")


def initialize_database(db: Database) -> None:
    db.create_mysql_database_if_needed()
    with db.session() as conn:
        cur = conn.cursor()
        for statement in SCHEMA_TABLES:
            cur.execute(db.adapt_sql(statement))
        _ensure_schema_columns(db, conn)
        _remove_sample_books(db, conn)


def _ensure_schema_columns(db: Database, conn: Any) -> None:
    expected = {
        "books": {
            "cover_path": "TEXT",
            "genre": "VARCHAR(100) NOT NULL DEFAULT ''",
            "market_channel": "VARCHAR(100) NOT NULL DEFAULT '中国网文男频爽文'",
            "target_reader": "TEXT NOT NULL DEFAULT ''",
            "pov_policy": "VARCHAR(100) NOT NULL DEFAULT 'third_limited'",
            "target_chars_min": "INTEGER NOT NULL DEFAULT 2200",
            "target_chars_max": "INTEGER NOT NULL DEFAULT 3200",
            "story_mainline": "TEXT NOT NULL DEFAULT ''",
            "worldbuilding": "TEXT NOT NULL DEFAULT ''",
            "imported_outline": "TEXT NOT NULL DEFAULT ''",
            "book_outline": "TEXT NOT NULL DEFAULT ''",
            "estimated_total_words": "INTEGER NOT NULL DEFAULT 1000000",
            "outline_locked": "INTEGER NOT NULL DEFAULT 0",
            "outline_confirmed_at": "TIMESTAMP NULL",
            "current_chapter_no": "INTEGER NOT NULL DEFAULT 0",
            "author_profile_id": "INTEGER",
            "editor_profile_id": "INTEGER",
            "book_author_profile_id": "INTEGER",
            "book_editor_profile_id": "INTEGER",
        },
        "chapter_plans": {
            "batch_id": "INTEGER",
            "plot_summary": "TEXT NOT NULL DEFAULT ''",
            "target_chars": "INTEGER NOT NULL DEFAULT 2600",
            "review_rounds": "INTEGER NOT NULL DEFAULT 0",
            "unique_task": "TEXT NOT NULL DEFAULT ''",
            "core_event": "TEXT NOT NULL DEFAULT ''",
            "tech_progression": "TEXT NOT NULL DEFAULT ''",
            "character_roles": "TEXT NOT NULL DEFAULT ''",
            "antagonist_move": "TEXT NOT NULL DEFAULT ''",
            "external_pressure": "TEXT NOT NULL DEFAULT ''",
            "irreversible_change": "TEXT NOT NULL DEFAULT ''",
            "ending_hook": "TEXT NOT NULL DEFAULT ''",
            "no_repeat_guard": "TEXT NOT NULL DEFAULT ''",
            "manual_edited": "INTEGER NOT NULL DEFAULT 0",
        },
        "volumes": {
            "estimated_words": "INTEGER NOT NULL DEFAULT 200000",
            "core_conflict": "TEXT NOT NULL DEFAULT ''",
            "stage_payoff": "TEXT NOT NULL DEFAULT ''",
            "character_progression": "TEXT NOT NULL DEFAULT ''",
            "foreshadowing_plan": "TEXT NOT NULL DEFAULT ''",
            "manual_edited": "INTEGER NOT NULL DEFAULT 0",
        },
        "story_arcs": {
            "cause": "TEXT NOT NULL DEFAULT ''",
            "process": "TEXT NOT NULL DEFAULT ''",
            "result": "TEXT NOT NULL DEFAULT ''",
            "payoff": "TEXT NOT NULL DEFAULT ''",
            "character_change": "TEXT NOT NULL DEFAULT ''",
            "foreshadowing_progress": "TEXT NOT NULL DEFAULT ''",
            "recommended_chapters": "INTEGER NOT NULL DEFAULT 5",
            "status": "VARCHAR(50) NOT NULL DEFAULT 'planned'",
            "manual_edited": "INTEGER NOT NULL DEFAULT 0",
        },
        "chapter_batches": {
            "volume_id": "INTEGER",
            "arc_id": "INTEGER",
            "recommended_count": "INTEGER NOT NULL DEFAULT 5",
            "author_count": "INTEGER NOT NULL DEFAULT 5",
        },
        "chapter_candidates": {
            "validation_errors": "TEXT NOT NULL DEFAULT ''",
            "source": "VARCHAR(50) NOT NULL DEFAULT 'planner'",
            "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        },
        "chapter_bodies": {
            "export_id": "INTEGER",
        },
        "production_settings": {
            "pov_policy": "VARCHAR(100) NOT NULL DEFAULT 'third_limited'",
            "hook_policy": "TEXT NOT NULL DEFAULT ''",
            "pacing_policy": "TEXT NOT NULL DEFAULT ''",
        },
        "characters": {
            "biography": "TEXT NOT NULL DEFAULT ''",
        },
        "continuity_memories": {
            "source_export_id": "INTEGER",
            "is_current": "INTEGER NOT NULL DEFAULT 1",
            "compression_mode": "VARCHAR(50) NOT NULL DEFAULT 'structured_budget'",
            "token_budget": "INTEGER NOT NULL DEFAULT 1200",
            "retrieval_count": "INTEGER NOT NULL DEFAULT 0",
            "last_used_at": "TIMESTAMP NULL",
        },
        "continuity_atoms": {
            "source_export_id": "INTEGER",
            "characters": "TEXT NOT NULL DEFAULT ''",
            "foreshadowing_tags": "TEXT NOT NULL DEFAULT ''",
            "confidence": "REAL NOT NULL DEFAULT 0.6",
            "subject_key": "VARCHAR(255) NOT NULL DEFAULT ''",
            "supersedes_atom_id": "INTEGER",
            "relevance_tags": "TEXT NOT NULL DEFAULT ''",
        },
        "chapter_state_snapshots": {
            "supersedes_snapshot_id": "INTEGER",
            "version": "INTEGER NOT NULL DEFAULT 1",
            "snapshot_json": "TEXT NOT NULL DEFAULT ''",
        },
        "chapter_transitions": {
            "supersedes_transition_id": "INTEGER",
            "version": "INTEGER NOT NULL DEFAULT 1",
        },
        "editorial_decisions": {
            "draft_id": "INTEGER",
            "score": "INTEGER NOT NULL DEFAULT 0",
        },
        "official_canon": {
            "source_snapshot_id": "INTEGER",
            "supersedes_canon_id": "INTEGER",
            "version": "INTEGER NOT NULL DEFAULT 1",
        },
        "pipeline_runs": {
            "error": "TEXT NOT NULL DEFAULT ''",
        },
        "workflow_runs": {
            "current_step": "VARCHAR(100) NOT NULL DEFAULT ''",
            "progress": "INTEGER NOT NULL DEFAULT 0",
            "error": "TEXT NOT NULL DEFAULT ''",
            "payload": "TEXT NOT NULL DEFAULT ''",
            "finished_at": "TIMESTAMP NULL",
        },
        "workflow_events": {
            "payload": "TEXT NOT NULL DEFAULT ''",
        },
        "export_versions": {
            "body_hash": "VARCHAR(128) NOT NULL DEFAULT ''",
            "source_chapters": "TEXT NOT NULL DEFAULT ''",
        },
    }
    cur = conn.cursor()
    if db.settings.using_mysql:
        for table, columns in expected.items():
            for column, definition in columns.items():
                cur.execute(f"SHOW COLUMNS FROM {table} LIKE %s", (column,))
                if cur.fetchone() is None:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {db.adapt_sql(definition)}")
        _ensure_mysql_longtext_columns(cur)
        return
    for table, columns in expected.items():
        cur.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cur.fetchall()}
        for column, definition in columns.items():
            if column not in existing:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _ensure_mysql_longtext_columns(cur: Any) -> None:
    longtext_columns = {
        "artifacts": ["content"],
        "chapter_bodies": ["body"],
        "continuity_memories": ["content"],
        "continuity_atoms": ["content"],
        "drift_reports": ["content"],
        "chapter_candidates": ["work_order", "validation_errors"],
        "chapter_tasks": ["opening_state", "mission", "definition_of_done", "scene_route", "irreversible_change", "handoff_to_next", "forbidden_future"],
        "chapter_state_snapshots": ["opening_state", "closing_state", "unit_state", "style_signature", "snapshot_json"],
        "chapter_transitions": ["from_state", "to_state", "transition_summary"],
        "editorial_decisions": ["evidence", "required_fixes"],
        "construction_packets": ["content"],
        "chapter_drafts": ["content"],
        "rework_tickets": ["required_fixes"],
        "workflow_runs": ["error", "payload"],
        "workflow_events": ["payload"],
        "official_canon": ["content"],
        "canonized_events": ["content"],
        "ledger_update_candidates": ["content"],
        "character_states": ["state"],
        "relationship_states": ["state"],
        "foreshadowing_ledger": ["content"],
        "setting_ledger": ["content"],
        "progression_ledger": ["content"],
    }
    for table, columns in longtext_columns.items():
        for column in columns:
            cur.execute(f"SHOW COLUMNS FROM {table} LIKE %s", (column,))
            row = cur.fetchone()
            if not row:
                continue
            column_type = str(row.get("Type") if isinstance(row, dict) else row[1]).lower()
            if column_type != "longtext":
                cur.execute(f"ALTER TABLE {table} MODIFY COLUMN {column} LONGTEXT NOT NULL")


def _remove_sample_books(db: Database, conn: Any) -> None:
    ph = db.placeholder()
    cur = conn.cursor()
    cur.execute(f"SELECT id FROM books WHERE status = {ph}", ("sample",))
    ids = [int(dict(row)["id"] if not isinstance(row, dict) else row["id"]) for row in cur.fetchall()]
    if not ids:
        return
    tables = [
        "volumes",
        "story_arcs",
        "chapter_batches",
        "chapter_candidates",
        "chapter_plans",
        "chapter_tasks",
        "chapter_state_snapshots",
        "chapter_transitions",
        "editorial_decisions",
        "model_call_logs",
        "production_runs",
        "workflow_runs",
        "workflow_events",
        "construction_packets",
        "chapter_drafts",
        "rework_tickets",
        "human_approval_logs",
        "official_canon",
        "canonized_events",
        "ledger_update_candidates",
        "character_states",
        "relationship_states",
        "foreshadowing_ledger",
        "setting_ledger",
        "progression_ledger",
        "style_profiles",
        "production_settings",
        "book_author_profiles",
        "book_editor_profiles",
        "characters",
        "relationships",
        "foreshadowings",
        "canon_facts",
        "visibility_rules",
        "artifacts",
        "chapter_bodies",
        "pipeline_runs",
        "rewrite_tasks",
        "continuity_memories",
        "continuity_atoms",
        "memory_retrieval_logs",
        "drift_reports",
        "export_records",
        "export_versions",
        "events",
    ]
    for book_id in ids:
        for table in tables:
            cur.execute(f"DELETE FROM {table} WHERE book_id = {ph}", (book_id,))
        cur.execute(f"DELETE FROM books WHERE id = {ph}", (book_id,))
