from __future__ import annotations

from app.config import get_settings
from app.llm import LlmClient
from app.services import Pipeline
from app.storage import Database, Repository, initialize_database


def build_runtime() -> tuple[Repository, Pipeline]:
    settings = get_settings()
    db = Database(settings)
    initialize_database(db)
    repo = Repository(db)
    repo.resolve_generation_errors_for_existing_bodies()
    return repo, Pipeline(repo, LlmClient(settings))
