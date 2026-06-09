from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path | None = None) -> None:
    env_path = path or PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    db_backend: str
    sqlite_path: Path
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_database: str
    llm_api_key: str
    llm_base_url: str
    llm_default_model: str
    llm_outline_model: str
    llm_writer_model: str
    llm_editor_model: str
    llm_timeout: int
    llm_mode: str
    app_host: str
    app_port: int

    @property
    def using_mysql(self) -> bool:
        return self.db_backend == "mysql"


def get_settings() -> Settings:
    load_env()
    llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("ZHIPUAI_API_KEY", "")
    raw_mode = (os.getenv("LLM_MODE") or "").strip()
    mode_as_model = raw_mode and raw_mode.lower() not in {"mock", "openai", "compatible", "zhipu"}
    default_model = os.getenv("LLM_DEFAULT_MODEL") or os.getenv("ZHIPUAI_MODEL") or (raw_mode if mode_as_model else "glm-4.5")
    llm_mode = "openai" if mode_as_model else (raw_mode or ("openai" if llm_api_key else "mock")).lower()
    sqlite_value = os.getenv("SQLITE_PATH", "").strip()
    if sqlite_value:
        sqlite_path = Path(sqlite_value)
        if not sqlite_path.is_absolute():
            sqlite_path = PROJECT_ROOT / sqlite_path
    else:
        sqlite_path = Path(tempfile.gettempdir()) / "fiction_architect" / "fiction_architect.db"
    return Settings(
        db_backend=os.getenv("DB_BACKEND", "sqlite").lower(),
        sqlite_path=sqlite_path,
        mysql_host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        mysql_port=int(os.getenv("MYSQL_PORT", "3306")),
        mysql_user=os.getenv("MYSQL_USER", ""),
        mysql_password=os.getenv("MYSQL_PASSWORD", ""),
        mysql_database=os.getenv("MYSQL_DATABASE", "fiction_architect"),
        llm_api_key=llm_api_key,
        llm_base_url=os.getenv("LLM_BASE_URL") or os.getenv("ZHIPUAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions"),
        llm_default_model=default_model,
        llm_outline_model=os.getenv("LLM_OUTLINE_MODEL", "qwen-max"),
        llm_writer_model=os.getenv("LLM_WRITER_MODEL", default_model),
        llm_editor_model=os.getenv("LLM_EDITOR_MODEL", default_model),
        llm_timeout=int(os.getenv("LLM_TIMEOUT") or os.getenv("ZHIPUAI_TIMEOUT", "60")),
        llm_mode=llm_mode,
        app_host=os.getenv("APP_HOST", "127.0.0.1"),
        app_port=int(os.getenv("APP_PORT", "8010")),
    )
