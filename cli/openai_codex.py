import sys

from rich.console import Console

from tradingagents.auth import (
    OPENAI_CODEX_PROVIDER,
    OpenAICodexAuthError,
    OpenAICodexProfileNotFound,
    OpenAICodexReauthRequiredError,
    get_active_openai_codex_profile,
    login_openai_codex,
)


def ensure_openai_codex_analysis_auth(
    config: dict,
    console: Console | None = None,
    interactive: bool | None = None,
) -> dict:
    if config.get("llm_provider", "").lower() != OPENAI_CODEX_PROVIDER:
        return config

    console = console or Console()
    interactive = (
        sys.stdin.isatty() and sys.stdout.isatty()
        if interactive is None
        else interactive
    )

    requested_profile_id = config.get("auth_profile_id")

    try:
        profile_id, _ = get_active_openai_codex_profile(requested_profile_id)
    except OpenAICodexProfileNotFound as exc:
        if not interactive:
            raise OpenAICodexAuthError(
                "No ChatGPT OAuth profile is available for `openai-codex`. "
                "Run `tradingagents auth login --provider openai-codex` first."
            ) from exc
        console.print(
            "[yellow]No ChatGPT OAuth profile found. Starting OpenAI Codex login...[/yellow]"
        )
        profile_id, _ = login_openai_codex(
            profile_id=requested_profile_id,
            print_func=console.print,
        )
    except OpenAICodexReauthRequiredError as exc:
        raise OpenAICodexAuthError(
            "ChatGPT OAuth credentials need to be refreshed manually. "
            "Run `tradingagents auth login --provider openai-codex` again."
        ) from exc

    config["auth_profile_id"] = profile_id
    return config

