import json
import os
from pathlib import Path

from .constants import (
    AUTH_LOCK_FILENAME,
    AUTH_PROFILE_FILENAME,
    AUTH_STORE_VERSION,
    STATE_DIR_ENV,
)


def resolve_state_dir(state_dir: str | None = None) -> Path:
    raw = state_dir or os.getenv(STATE_DIR_ENV) or "~/.tradingagents"
    path = Path(raw).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_auth_store_path(state_dir: str | None = None) -> Path:
    return resolve_state_dir(state_dir) / AUTH_PROFILE_FILENAME


def resolve_auth_lock_path(state_dir: str | None = None) -> Path:
    return resolve_state_dir(state_dir) / AUTH_LOCK_FILENAME


def resolve_codex_auth_path(path: str | None = None) -> Path:
    return Path(path or "~/.codex/auth.json").expanduser()


def ensure_auth_store_file(state_dir: str | None = None) -> Path:
    path = resolve_auth_store_path(state_dir)
    if path.exists():
        return path

    path.write_text(
        json.dumps({"version": AUTH_STORE_VERSION, "profiles": {}}, indent=2),
        encoding="utf-8",
    )
    return path

