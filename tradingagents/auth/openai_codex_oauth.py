import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from .codex_import import import_codex_auth_profile
from .constants import (
    OPENAI_CODEX_AUTHORIZE_URL,
    OPENAI_CODEX_CALLBACK_HOST,
    OPENAI_CODEX_CALLBACK_PATH,
    OPENAI_CODEX_CALLBACK_PORT,
    OPENAI_CODEX_CLIENT_ID,
    OPENAI_CODEX_PROVIDER,
    OPENAI_CODEX_SCOPES,
    OPENAI_CODEX_TOKEN_URL,
)
from .exceptions import (
    OpenAICodexAuthError,
    OpenAICodexOAuthStateError,
    OpenAICodexProfileNotFound,
    OpenAICodexReauthRequiredError,
)
from .store import (
    OAuthProfile,
    auth_store_lock,
    build_profile_id,
    get_profile,
    is_profile_expired,
    list_profiles,
    load_auth_store,
    pick_profile_id,
    save_auth_store,
    upsert_profile,
)
from .token_utils import get_jwt_email, get_jwt_expiry_ms


def get_callback_url() -> str:
    return (
        f"http://{OPENAI_CODEX_CALLBACK_HOST}:{OPENAI_CODEX_CALLBACK_PORT}"
        f"{OPENAI_CODEX_CALLBACK_PATH}"
    )


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return verifier, challenge


def build_openai_codex_authorization_url(
    state: str,
    code_challenge: str,
    redirect_uri: str | None = None,
) -> str:
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": OPENAI_CODEX_CLIENT_ID,
            "redirect_uri": redirect_uri or get_callback_url(),
            "scope": OPENAI_CODEX_SCOPES,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "codex_cli_simplified_flow": "true",
            "id_token_add_organizations": "true",
        }
    )
    return f"{OPENAI_CODEX_AUTHORIZE_URL}?{query}"


def parse_oauth_callback_input(raw_value: str, expected_state: str) -> dict[str, str]:
    value = (raw_value or "").strip()
    if not value:
        raise OpenAICodexOAuthStateError("Missing OAuth callback input.")

    if value.startswith("http://") or value.startswith("https://"):
        parsed = urllib.parse.urlparse(value)
        query = urllib.parse.parse_qs(parsed.query)
    else:
        query = urllib.parse.parse_qs(value.lstrip("?"))

    code = query.get("code", [None])[0]
    state = query.get("state", [None])[0]
    error = query.get("error", [None])[0]
    error_description = query.get("error_description", [None])[0]

    if error:
        detail = f"{error}: {error_description}" if error_description else str(error)
        raise OpenAICodexAuthError(f"OAuth login failed: {detail}")
    if not state:
        raise OpenAICodexOAuthStateError("OAuth callback did not include state.")
    if state != expected_state:
        raise OpenAICodexOAuthStateError("OAuth callback state did not match the login session.")
    if not code:
        raise OpenAICodexAuthError("OAuth callback did not include an authorization code.")

    return {"code": code, "state": state}


def _build_profile_from_token_response(
    payload: dict,
    previous_profile: OAuthProfile | None = None,
) -> OAuthProfile:
    access = payload.get("access_token")
    if not isinstance(access, str) or not access:
        raise OpenAICodexAuthError("OpenAI OAuth response did not include an access token.")

    refresh = payload.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        refresh = previous_profile.get("refresh") if previous_profile else None
    if not isinstance(refresh, str) or not refresh:
        raise OpenAICodexReauthRequiredError(
            "OpenAI OAuth response did not include a refresh token. Please log in again."
        )

    account_id = payload.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        if previous_profile and isinstance(previous_profile.get("account_id"), str):
            account_id = previous_profile["account_id"]
        else:
            account_id = None

    expires_in = payload.get("expires_in")
    expires = None
    if isinstance(expires_in, (int, float)):
        expires = int((time.time() + int(expires_in)) * 1000)
    if expires is None:
        expires = get_jwt_expiry_ms(access)

    email = get_jwt_email(access)
    if not email and previous_profile:
        previous_email = previous_profile.get("email")
        if isinstance(previous_email, str):
            email = previous_email

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

    return profile


def _post_token_request(form: dict[str, str]) -> dict:
    try:
        response = requests.post(
            OPENAI_CODEX_TOKEN_URL,
            data=form,
            headers={"Accept": "application/json"},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise OpenAICodexAuthError(f"OpenAI OAuth token request failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {"error": response.text}

    if response.status_code >= 400:
        error = payload.get("error") or response.reason
        description = payload.get("error_description") or payload.get("message")
        detail = f"{error}: {description}" if description else str(error)
        raise OpenAICodexAuthError(f"OpenAI OAuth token exchange failed: {detail}")

    return payload


def exchange_authorization_code(
    code: str,
    code_verifier: str,
    redirect_uri: str | None = None,
) -> OAuthProfile:
    payload = _post_token_request(
        {
            "grant_type": "authorization_code",
            "client_id": OPENAI_CODEX_CLIENT_ID,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri or get_callback_url(),
        }
    )
    return _build_profile_from_token_response(payload)


def exchange_refresh_token(
    refresh_token: str,
    previous_profile: OAuthProfile | None = None,
) -> OAuthProfile:
    try:
        payload = _post_token_request(
            {
                "grant_type": "refresh_token",
                "client_id": OPENAI_CODEX_CLIENT_ID,
                "refresh_token": refresh_token,
            }
        )
    except OpenAICodexAuthError as exc:
        raise OpenAICodexReauthRequiredError(
            f"OpenAI Codex OAuth refresh failed. Please run `tradingagents auth login --provider openai-codex` again. {exc}"
        ) from exc

    return _build_profile_from_token_response(payload, previous_profile=previous_profile)


def refresh_openai_codex_profile(
    profile_id: str,
    state_dir: str | None = None,
    force: bool = False,
) -> tuple[str, OAuthProfile]:
    with auth_store_lock(state_dir):
        store = load_auth_store(state_dir)
        raw_profile = store["profiles"].get(profile_id)
        if not isinstance(raw_profile, dict):
            raise OpenAICodexProfileNotFound(f"OpenAI Codex OAuth profile not found: {profile_id}")

        profile: OAuthProfile = raw_profile
        if not force and not is_profile_expired(profile):
            return profile_id, profile

        refresh_token = profile.get("refresh")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise OpenAICodexReauthRequiredError(
                "OpenAI Codex OAuth profile does not have a refresh token. Please sign in again."
            )

        refreshed = exchange_refresh_token(refresh_token, previous_profile=profile)
        store["profiles"][profile_id] = refreshed
        save_auth_store(store, state_dir)
        return profile_id, refreshed


def get_openai_codex_profile(
    profile_id: str | None = None,
    state_dir: str | None = None,
    auto_import: bool = True,
) -> tuple[str, OAuthProfile]:
    selected_profile_id = pick_profile_id(
        explicit_profile_id=profile_id,
        provider=OPENAI_CODEX_PROVIDER,
        state_dir=state_dir,
    )
    if selected_profile_id:
        profile = get_profile(selected_profile_id, state_dir)
        if profile:
            return selected_profile_id, profile

    if auto_import:
        imported = import_codex_auth_profile(state_dir=state_dir, profile_id=profile_id)
        if imported:
            return imported

    available = ", ".join(profile_id for profile_id, _ in list_profiles(OPENAI_CODEX_PROVIDER, state_dir))
    message = "No OpenAI Codex OAuth profile is available."
    if available:
        message += f" Available profiles: {available}"
    raise OpenAICodexProfileNotFound(message)


def get_active_openai_codex_profile(
    profile_id: str | None = None,
    state_dir: str | None = None,
    auto_import: bool = True,
) -> tuple[str, OAuthProfile]:
    selected_profile_id, profile = get_openai_codex_profile(
        profile_id=profile_id,
        state_dir=state_dir,
        auto_import=auto_import,
    )
    if is_profile_expired(profile):
        return refresh_openai_codex_profile(selected_profile_id, state_dir=state_dir)
    return selected_profile_id, profile


def start_local_callback_listener(timeout_seconds: float = 180.0) -> str | None:
    event = threading.Event()
    callback_url: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if not self.path.startswith(OPENAI_CODEX_CALLBACK_PATH):
                self.send_response(404)
                self.end_headers()
                return

            callback_url["value"] = (
                f"http://{OPENAI_CODEX_CALLBACK_HOST}:{OPENAI_CODEX_CALLBACK_PORT}{self.path}"
            )
            body = (
                "<html><body><h1>TradingAgents login complete</h1>"
                "<p>You can close this window and return to the terminal.</p></body></html>"
            )
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            event.set()

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

    try:
        server = ThreadingHTTPServer(
            (OPENAI_CODEX_CALLBACK_HOST, OPENAI_CODEX_CALLBACK_PORT),
            CallbackHandler,
        )
    except OSError:
        return None

    server.timeout = 0.5

    def serve() -> None:
        deadline = time.time() + timeout_seconds
        while not event.is_set() and time.time() < deadline:
            server.handle_request()
        server.server_close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    deadline = time.time() + timeout_seconds
    while not event.is_set() and time.time() < deadline:
        time.sleep(0.1)

    if not event.is_set():
        return None

    return callback_url.get("value")


def login_openai_codex(
    state_dir: str | None = None,
    profile_id: str | None = None,
    headless: bool = False,
    timeout_seconds: float = 180.0,
    codex_auth_path: str | None = None,
    input_func=input,
    print_func=print,
) -> tuple[str, OAuthProfile]:
    imported = import_codex_auth_profile(
        state_dir=state_dir,
        profile_id=profile_id,
        codex_auth_path=codex_auth_path,
    )
    if imported:
        return imported

    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(24)
    redirect_uri = get_callback_url()
    auth_url = build_openai_codex_authorization_url(
        state=state,
        code_challenge=code_challenge,
        redirect_uri=redirect_uri,
    )

    print_func("Open the following URL to complete ChatGPT OAuth:")
    print_func(auth_url)

    if not headless:
        try:
            webbrowser.open(auth_url)
        except Exception:
            pass

    callback_value = None if headless else start_local_callback_listener(timeout_seconds=timeout_seconds)
    if not callback_value:
        callback_value = input_func(
            "Paste the full redirect URL, or `code=...&state=...`: "
        ).strip()
        if "code=" not in callback_value and "state=" not in callback_value:
            code = callback_value
            state_value = input_func("Paste the returned state value: ").strip()
            callback_value = f"code={code}&state={state_value}"

    parsed = parse_oauth_callback_input(callback_value, expected_state=state)
    profile = exchange_authorization_code(
        code=parsed["code"],
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
    )
    selected_profile_id = profile_id or build_profile_id(profile.get("email"))
    upsert_profile(selected_profile_id, profile, state_dir=state_dir)
    return selected_profile_id, profile
