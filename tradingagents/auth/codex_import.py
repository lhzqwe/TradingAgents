import json

from .constants import OPENAI_CODEX_PROVIDER
from .paths import resolve_codex_auth_path
from .store import OAuthProfile, build_profile_id, upsert_profile
from .token_utils import get_jwt_email, get_jwt_expiry_ms


def load_codex_auth_tokens(codex_auth_path: str | None = None) -> dict | None:
    path = resolve_codex_auth_path(codex_auth_path)
    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    auth_mode = raw.get("auth_mode")
    if auth_mode not in (None, "chatgpt"):
        return None

    tokens = raw.get("tokens")
    if not isinstance(tokens, dict):
        return None
    return tokens


def import_codex_auth_profile(
    state_dir: str | None = None,
    profile_id: str | None = None,
    codex_auth_path: str | None = None,
) -> tuple[str, OAuthProfile] | None:
    tokens = load_codex_auth_tokens(codex_auth_path)
    if not tokens:
        return None

    access = tokens.get("access_token")
    refresh = tokens.get("refresh_token")
    if not isinstance(access, str) or not access:
        return None
    if not isinstance(refresh, str) or not refresh:
        return None

    email = get_jwt_email(access)
    expires = get_jwt_expiry_ms(access)
    account_id = tokens.get("account_id")

    profile: OAuthProfile = {
        "type": "oauth",
        "provider": OPENAI_CODEX_PROVIDER,
        "access": access,
        "refresh": refresh,
    }
    if isinstance(expires, int):
        profile["expires"] = expires
    if isinstance(email, str) and email:
        profile["email"] = email
    if isinstance(account_id, str) and account_id:
        profile["account_id"] = account_id

    selected_profile_id = profile_id or build_profile_id(email)
    upsert_profile(selected_profile_id, profile, state_dir=state_dir)
    return selected_profile_id, profile

