from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from .config import get_config


class TigerOpenRecoverableError(Exception):
    """Base class for Tiger Open recoverable routing errors."""


class TigerOpenConfigError(TigerOpenRecoverableError):
    """Raised when Tiger Open configuration is incomplete."""


class TigerOpenAuthError(TigerOpenRecoverableError):
    """Raised when Tiger Open authentication fails."""


class TigerOpenPermissionError(TigerOpenRecoverableError):
    """Raised when Tiger Open quote permissions are missing."""


class TigerOpenRateLimitError(TigerOpenRecoverableError):
    """Raised when Tiger Open rate limits are hit."""


class TigerOpenUnavailableError(TigerOpenRecoverableError):
    """Raised when Tiger Open SDK or endpoint is unavailable."""


def get_tigeropen_settings() -> dict:
    config = get_config()
    tiger_config = dict(config.get("tigeropen", {}))
    default_props_path = _get_default_props_path()

    tiger_config["props_path"] = (
        tiger_config.get("props_path")
        or os.getenv("TIGER_CONFIG_PATH")
        or default_props_path
    )
    tiger_config["private_key_path"] = tiger_config.get("private_key_path") or os.getenv("TIGER_PRIVATE_KEY_PATH")
    tiger_config["private_key_pk1"] = tiger_config.get("private_key_pk1") or os.getenv("TIGER_PRIVATE_KEY_PK1")
    tiger_config["tiger_id"] = tiger_config.get("tiger_id") or os.getenv("TIGER_ID")
    tiger_config["account"] = tiger_config.get("account") or os.getenv("TIGER_ACCOUNT")
    tiger_config["license"] = tiger_config.get("license") or os.getenv("TIGER_LICENSE")
    tiger_config["secret_key"] = tiger_config.get("secret_key") or os.getenv("TIGER_SECRET_KEY")
    tiger_config["lang"] = tiger_config.get("lang") or "en_US"
    tiger_config["right"] = tiger_config.get("right") or "BR"
    tiger_config["with_fundamental"] = tiger_config.get("with_fundamental", True)
    tiger_config["indicator_history_years"] = tiger_config.get("indicator_history_years", 15)
    tiger_config["symbol_overrides"] = tiger_config.get("symbol_overrides", {})
    return tiger_config


def get_tiger_quote_client():
    settings = get_tigeropen_settings()
    client_key = _settings_to_cache_key(settings)
    return _create_tiger_quote_client(client_key)


def resolve_tiger_symbol(symbol: str) -> str:
    overrides = get_tigeropen_settings().get("symbol_overrides", {}) or {}
    if symbol in overrides:
        return str(overrides[symbol])
    if symbol.upper() in overrides:
        return str(overrides[symbol.upper()])
    return symbol


@lru_cache(maxsize=8)
def _create_tiger_quote_client(client_key: tuple):
    try:
        from tigeropen.quote.quote_client import QuoteClient
        from tigeropen.tiger_open_config import TigerOpenClientConfig
    except ModuleNotFoundError as exc:
        raise TigerOpenUnavailableError(
            "Tiger Open SDK is not installed. Install `tigeropen` to enable this vendor."
        ) from exc

    settings = {
        "props_path": client_key[0],
        "private_key_path": client_key[1],
        "private_key_pk1": client_key[2],
        "tiger_id": client_key[3],
        "account": client_key[4],
        "license": client_key[5],
        "secret_key": client_key[6],
        "lang": client_key[7],
    }

    client_config = _build_client_config(TigerOpenClientConfig, settings)

    try:
        return QuoteClient(client_config, is_grab_permission=False)
    except Exception as exc:
        raise _map_tiger_exception(exc) from exc


def _build_client_config(config_cls, settings: dict):
    props_path = _normalize_props_path(settings.get("props_path"))
    if props_path:
        return config_cls(props_path=props_path)

    required = {
        "tiger_id": settings.get("tiger_id"),
        "account": settings.get("account"),
        "license": settings.get("license"),
    }
    missing = [key for key, value in required.items() if not value]

    private_key = _load_private_key(
        settings.get("private_key_path"),
        settings.get("private_key_pk1"),
    )
    if not private_key:
        missing.append("private_key_pk1/private_key_path")

    if missing:
        raise TigerOpenConfigError(
            "Tiger Open credentials are incomplete. Missing: " + ", ".join(missing)
        )

    client_config = config_cls()
    client_config.tiger_id = required["tiger_id"]
    client_config.account = required["account"]
    client_config.license = required["license"]
    client_config.private_key = private_key
    client_config.language = settings.get("lang") or "en_US"

    secret_key = settings.get("secret_key")
    if secret_key:
        client_config.secret_key = secret_key

    return client_config


def _load_private_key(private_key_path: str | None, private_key_pk1: str | None) -> str:
    if private_key_pk1:
        return str(private_key_pk1).strip()

    if not private_key_path:
        return ""

    path = Path(private_key_path).expanduser()
    if not path.exists():
        raise TigerOpenConfigError(
            f"Tiger Open private key path does not exist: {path}"
        )

    return path.read_text(encoding="utf-8").strip()


def _normalize_props_path(props_path: str | None) -> str | None:
    if not props_path:
        return None

    path = Path(props_path).expanduser()
    if path.is_file():
        return str(path.parent)
    if path.exists():
        return str(path)
    raise TigerOpenConfigError(
        f"Tiger Open props path does not exist: {path}"
    )


def _get_default_props_path() -> str | None:
    state_dir = os.getenv("TRADINGAGENTS_STATE_DIR")
    if not state_dir:
        state_dir = str(Path.home() / ".tradingagents")

    default_file = Path(state_dir) / "tiger" / "tiger_openapi_config.properties"
    if default_file.exists():
        return str(default_file)
    return None


def _settings_to_cache_key(settings: dict) -> tuple:
    return (
        settings.get("props_path"),
        settings.get("private_key_path"),
        settings.get("private_key_pk1"),
        settings.get("tiger_id"),
        settings.get("account"),
        settings.get("license"),
        settings.get("secret_key"),
        settings.get("lang"),
    )


def _map_tiger_exception(exc: Exception) -> TigerOpenRecoverableError:
    try:
        from tigeropen.common.exceptions import ApiException
    except ModuleNotFoundError:
        ApiException = None  # type: ignore[assignment]

    if isinstance(exc, TigerOpenRecoverableError):
        return exc

    if ApiException and isinstance(exc, ApiException):
        message = str(exc)
        lowered = message.lower()
        if getattr(exc, "code", None) == 4 or "rate limit" in lowered:
            return TigerOpenRateLimitError(message)
        if "permission" in lowered:
            return TigerOpenPermissionError(message)
        if "auth" in lowered or "signature" in lowered or "token" in lowered:
            return TigerOpenAuthError(message)
        return TigerOpenUnavailableError(message)

    lowered = str(exc).lower()
    if "permission" in lowered:
        return TigerOpenPermissionError(str(exc))
    if "auth" in lowered or "signature" in lowered or "token" in lowered:
        return TigerOpenAuthError(str(exc))
    return TigerOpenUnavailableError(str(exc))
