import os

AUTH_STORE_VERSION = 1
AUTH_PROFILE_FILENAME = "auth-profiles.json"
AUTH_LOCK_FILENAME = "auth-profiles.lock"

STATE_DIR_ENV = "TRADINGAGENTS_STATE_DIR"

OPENAI_CODEX_PROVIDER = "openai-codex"
OPENAI_CODEX_DEFAULT_PROFILE_ID = f"{OPENAI_CODEX_PROVIDER}:default"

OPENAI_CODEX_CLIENT_ID = os.getenv(
    "TRADINGAGENTS_OPENAI_CODEX_CLIENT_ID",
    "app_EMoamEEZ73f0CkXaXp7hrann",
)
OPENAI_CODEX_AUTHORIZE_URL = os.getenv(
    "TRADINGAGENTS_OPENAI_CODEX_AUTHORIZE_URL",
    "https://auth.openai.com/oauth/authorize",
)
OPENAI_CODEX_TOKEN_URL = os.getenv(
    "TRADINGAGENTS_OPENAI_CODEX_TOKEN_URL",
    "https://auth.openai.com/oauth/token",
)
OPENAI_CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
OPENAI_CODEX_SCOPES = (
    "openid profile email offline_access api.connectors.read api.connectors.invoke"
)

OPENAI_CODEX_CALLBACK_HOST = os.getenv(
    "TRADINGAGENTS_OPENAI_CODEX_CALLBACK_HOST",
    "127.0.0.1",
)
OPENAI_CODEX_CALLBACK_PORT = int(
    os.getenv("TRADINGAGENTS_OPENAI_CODEX_CALLBACK_PORT", "1455")
)
OPENAI_CODEX_CALLBACK_PATH = "/auth/callback"

