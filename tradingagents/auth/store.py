import json
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator, TypedDict

from .constants import (
    AUTH_STORE_VERSION,
    OPENAI_CODEX_DEFAULT_PROFILE_ID,
    OPENAI_CODEX_PROVIDER,
)
from .paths import ensure_auth_store_file, resolve_auth_lock_path, resolve_auth_store_path


class OAuthProfile(TypedDict, total=False):
    type: str
    provider: str
    access: str
    refresh: str
    expires: int
    email: str
    account_id: str


def _coerce_store(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"version": AUTH_STORE_VERSION, "profiles": {}}

    profiles = raw.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}

    version = raw.get("version")
    if not isinstance(version, int):
        version = AUTH_STORE_VERSION

    return {"version": version, "profiles": profiles}


def load_auth_store(state_dir: str | None = None) -> dict[str, Any]:
    path = ensure_auth_store_file(state_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = None
    return _coerce_store(raw)


def save_auth_store(store: dict[str, Any], state_dir: str | None = None) -> None:
    path = ensure_auth_store_file(state_dir)
    payload = _coerce_store(store)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@contextmanager
def auth_store_lock(
    state_dir: str | None = None,
    timeout_seconds: float = 10.0,
    poll_seconds: float = 0.1,
) -> Iterator[None]:
    lock_path = resolve_auth_lock_path(state_dir)
    fd = None
    start = time.monotonic()

    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            break
        except FileExistsError:
            if time.monotonic() - start >= timeout_seconds:
                raise TimeoutError(f"Timed out waiting for auth store lock: {lock_path}")
            time.sleep(poll_seconds)

    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def build_profile_id(email: str | None = None) -> str:
    if email:
        return f"{OPENAI_CODEX_PROVIDER}:{email}"
    return OPENAI_CODEX_DEFAULT_PROFILE_ID


def list_profiles(
    provider: str | None = None,
    state_dir: str | None = None,
) -> list[tuple[str, OAuthProfile]]:
    store = load_auth_store(state_dir)
    profiles: list[tuple[str, OAuthProfile]] = []
    for profile_id, profile in sorted(store["profiles"].items()):
        if not isinstance(profile, dict):
            continue
        if provider and profile.get("provider") != provider:
            continue
        profiles.append((profile_id, profile))
    return profiles


def get_profile(profile_id: str, state_dir: str | None = None) -> OAuthProfile | None:
    store = load_auth_store(state_dir)
    profile = store["profiles"].get(profile_id)
    if isinstance(profile, dict):
        return profile
    return None


def pick_profile_id(
    explicit_profile_id: str | None = None,
    provider: str = OPENAI_CODEX_PROVIDER,
    state_dir: str | None = None,
) -> str | None:
    if explicit_profile_id:
        return explicit_profile_id

    profiles = list_profiles(provider=provider, state_dir=state_dir)
    if not profiles:
        return None

    email_profiles = [
        profile_id
        for profile_id, _ in profiles
        if profile_id != OPENAI_CODEX_DEFAULT_PROFILE_ID
    ]
    if email_profiles:
        return email_profiles[0]

    default = next(
        (profile_id for profile_id, _ in profiles if profile_id == OPENAI_CODEX_DEFAULT_PROFILE_ID),
        None,
    )
    if default:
        return default

    return profiles[0][0]


def is_profile_expired(profile: OAuthProfile, skew_ms: int = 60_000) -> bool:
    expires = profile.get("expires")
    if not isinstance(expires, int):
        return False
    return expires <= int(time.time() * 1000) + skew_ms


def upsert_profile(
    profile_id: str,
    profile: OAuthProfile,
    state_dir: str | None = None,
) -> OAuthProfile:
    with auth_store_lock(state_dir):
        store = load_auth_store(state_dir)
        store["profiles"][profile_id] = profile
        save_auth_store(store, state_dir)
    return profile


def delete_profile(profile_id: str, state_dir: str | None = None) -> bool:
    with auth_store_lock(state_dir):
        store = load_auth_store(state_dir)
        if profile_id not in store["profiles"]:
            return False
        del store["profiles"][profile_id]
        save_auth_store(store, state_dir)
    return True

