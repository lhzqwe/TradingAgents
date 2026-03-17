import base64
import json
from typing import Any


def _decode_base64url(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def decode_jwt_payload(token: str) -> dict[str, Any]:
    if not token or token.count(".") < 2:
        raise ValueError("Invalid JWT token")

    payload = token.split(".")[1]
    decoded = _decode_base64url(payload)
    return json.loads(decoded.decode("utf-8"))


def get_jwt_expiry_ms(token: str) -> int | None:
    try:
        claims = decode_jwt_payload(token)
    except (ValueError, json.JSONDecodeError):
        return None

    exp = claims.get("exp")
    if isinstance(exp, (int, float)):
        return int(exp * 1000)
    return None


def get_jwt_email(token: str) -> str | None:
    try:
        claims = decode_jwt_payload(token)
    except (ValueError, json.JSONDecodeError):
        return None

    email = claims.get("email")
    if isinstance(email, str) and email:
        return email

    profile = claims.get("https://api.openai.com/profile")
    if isinstance(profile, dict):
        nested_email = profile.get("email")
        if isinstance(nested_email, str) and nested_email:
            return nested_email

    return None

