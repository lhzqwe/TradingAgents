import datetime

import typer
from rich.console import Console
from rich.table import Table

from tradingagents.auth import (
    OPENAI_CODEX_PROVIDER,
    delete_profile,
    is_profile_expired,
    list_profiles,
    login_openai_codex,
    pick_profile_id,
)

console = Console()
auth_app = typer.Typer(help="Manage TradingAgents auth profiles.")


def _require_openai_codex_provider(provider: str) -> str:
    normalized = provider.lower().strip()
    if normalized != OPENAI_CODEX_PROVIDER:
        raise typer.BadParameter(
            "Only `openai-codex` is currently supported for `tradingagents auth`."
        )
    return normalized


def _format_expiry(expires: int | None) -> str:
    if not isinstance(expires, int):
        return "--"
    return datetime.datetime.fromtimestamp(expires / 1000).strftime("%Y-%m-%d %H:%M:%S")


@auth_app.command("login")
def auth_login(
    provider: str = typer.Option(..., "--provider", help="Auth provider id."),
    profile: str | None = typer.Option(
        None, "--profile", help="Optional profile id override."
    ),
    headless: bool = typer.Option(
        False,
        "--headless",
        help="Disable localhost callback and paste the redirect URL manually.",
    ),
):
    _require_openai_codex_provider(provider)
    profile_id, saved_profile = login_openai_codex(
        profile_id=profile,
        headless=headless,
        print_func=console.print,
    )
    console.print(f"[green]Saved ChatGPT OAuth profile:[/green] {profile_id}")
    email = saved_profile.get("email")
    if isinstance(email, str) and email:
        console.print(f"[dim]Account:[/dim] {email}")


@auth_app.command("status")
def auth_status():
    profiles = list_profiles(provider=OPENAI_CODEX_PROVIDER)
    if not profiles:
        console.print("[yellow]No ChatGPT OAuth profiles found.[/yellow]")
        raise typer.Exit(code=0)

    table = Table(title="ChatGPT OAuth Profiles")
    table.add_column("Profile", overflow="fold")
    table.add_column("Email")
    table.add_column("Status")
    table.add_column("Expires")

    for profile_id, profile in profiles:
        email = profile.get("email") if isinstance(profile.get("email"), str) else "--"
        status = "expired" if is_profile_expired(profile) else "valid"
        table.add_row(profile_id, email, status, _format_expiry(profile.get("expires")))

    console.print(table)


@auth_app.command("logout")
def auth_logout(
    provider: str = typer.Option(..., "--provider", help="Auth provider id."),
    profile: str | None = typer.Option(
        None, "--profile", help="Optional profile id to remove."
    ),
):
    _require_openai_codex_provider(provider)
    profile_id = profile or pick_profile_id(provider=OPENAI_CODEX_PROVIDER)
    if not profile_id:
        console.print("[yellow]No ChatGPT OAuth profile found to remove.[/yellow]")
        raise typer.Exit(code=1)

    if not delete_profile(profile_id):
        console.print(f"[red]Profile not found:[/red] {profile_id}")
        raise typer.Exit(code=1)

    console.print(f"[green]Removed ChatGPT OAuth profile:[/green] {profile_id}")
