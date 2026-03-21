"""twitter-cli based X/Twitter social data fetching."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .config import get_config

_SCHEMA_VERSION = "1"


def get_social_posts_twitter_cli(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """Retrieve X/Twitter posts via the twitter-cli submodule."""
    config = get_config()
    twitter_config = config.get("twitter_cli", {})
    repo_root = Path(config["project_dir"]).resolve().parent
    submodule_path = _resolve_submodule_path(
        repo_root,
        str(twitter_config.get("submodule_path", "external/twitter-cli")),
    )
    query = _resolve_query(ticker, twitter_config.get("query_overrides", {}))
    timeout_seconds = float(twitter_config.get("timeout_seconds", 30))
    max_posts = max(int(twitter_config.get("max_posts", 20)), 1)
    search_product = str(twitter_config.get("search_product", "Latest"))

    if not _is_valid_submodule(submodule_path):
        return _fallback_social_report(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            query=query,
            reason=f"twitter-cli submodule not found at {submodule_path}",
        )

    status_result = _run_twitter_cli(
        ["status", "--json"],
        repo_root=repo_root,
        submodule_path=submodule_path,
        timeout_seconds=timeout_seconds,
    )
    status_payload, payload_error = _parse_payload(status_result)
    if payload_error:
        return _fallback_social_report(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            query=query,
            reason=payload_error,
        )
    if not status_payload.get("ok", False):
        return _fallback_social_report(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            query=query,
            reason=_payload_error_message(status_payload, status_result),
        )
    if status_result.returncode != 0:
        return _fallback_social_report(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            query=query,
            reason=_completed_process_error(status_result),
        )

    auth_user = _status_user_label(status_payload)
    until_date = (date.fromisoformat(end_date) + timedelta(days=1)).isoformat()
    search_result = _run_twitter_cli(
        [
            "search",
            query,
            "-t",
            search_product,
            "--since",
            start_date,
            "--until",
            until_date,
            "--exclude",
            "retweets",
            "--max",
            str(max_posts),
            "--json",
        ],
        repo_root=repo_root,
        submodule_path=submodule_path,
        timeout_seconds=timeout_seconds,
    )
    search_payload, payload_error = _parse_payload(search_result)
    if payload_error:
        return _fallback_social_report(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            query=query,
            reason=payload_error,
        )
    if not search_payload.get("ok", False):
        return _fallback_social_report(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            query=query,
            reason=_payload_error_message(search_payload, search_result),
        )
    if search_result.returncode != 0:
        return _fallback_social_report(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            query=query,
            reason=_completed_process_error(search_result),
        )

    posts = search_payload.get("data")
    if not isinstance(posts, list):
        return _fallback_social_report(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            query=query,
            reason="twitter-cli returned an unexpected payload for search results",
        )
    if len(posts) == 0:
        return _fallback_social_report(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            query=query,
            reason="twitter-cli returned zero X/Twitter posts for the requested query",
        )

    return _format_social_posts(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        query=query,
        auth_user=auth_user,
        posts=posts,
    )


def _resolve_submodule_path(repo_root: Path, submodule_path: str) -> Path:
    path = Path(submodule_path)
    if path.is_absolute():
        return path
    return (repo_root / path).resolve()


def _resolve_query(ticker: str, query_overrides: Any) -> str:
    if isinstance(query_overrides, dict):
        if ticker in query_overrides:
            return str(query_overrides[ticker])
        if ticker.upper() in query_overrides:
            return str(query_overrides[ticker.upper()])
    return f"${ticker.upper()}"


def _is_valid_submodule(submodule_path: Path) -> bool:
    return (submodule_path / "twitter_cli" / "cli.py").exists()


def _run_twitter_cli(
    args: list[str],
    *,
    repo_root: Path,
    submodule_path: Path,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = _prepend_pythonpath(
        str(submodule_path),
        env.get("PYTHONPATH"),
    )
    command = [sys.executable, "-m", "twitter_cli.cli", *args]
    return subprocess.run(
        command,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        env=env,
    )


def _prepend_pythonpath(new_path: str, existing: str | None) -> str:
    if not existing:
        return new_path
    return os.pathsep.join([new_path, existing])


def _parse_payload(
    result: subprocess.CompletedProcess[str],
) -> tuple[dict[str, Any], str | None]:
    stdout = (result.stdout or "").strip()
    if not stdout:
        return {}, _completed_process_error(result)

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {}, "twitter-cli returned malformed JSON output"

    if not isinstance(payload, dict):
        return {}, "twitter-cli returned a non-object JSON payload"
    if payload.get("schema_version") != _SCHEMA_VERSION:
        return {}, "twitter-cli returned an unsupported schema_version"
    if "ok" not in payload:
        return {}, "twitter-cli payload is missing the ok flag"
    return payload, None


def _completed_process_error(result: subprocess.CompletedProcess[str]) -> str:
    stderr = (result.stderr or "").strip()
    if stderr:
        return f"twitter-cli process failed: {stderr}"
    return f"twitter-cli process exited with code {result.returncode}"


def _payload_error_message(
    payload: dict[str, Any],
    result: subprocess.CompletedProcess[str],
) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        code = error.get("code", "api_error")
        message = error.get("message", "twitter-cli reported an error")
        return f"twitter-cli {code}: {message}"
    return _completed_process_error(result)


def _status_user_label(payload: dict[str, Any]) -> str:
    data = payload.get("data")
    if not isinstance(data, dict):
        return "unknown"
    user = data.get("user")
    if not isinstance(user, dict):
        return "unknown"
    screen_name = user.get("screenName") or user.get("screen_name")
    if screen_name:
        return f"@{screen_name}"
    name = user.get("name")
    if name:
        return str(name)
    return "unknown"


def _format_social_posts(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    query: str,
    auth_user: str,
    posts: list[Any],
) -> str:
    lines = [
        f"## X/Twitter Posts for {ticker}, from {start_date} to {end_date}:",
        "",
        f"- Query: `{query}`",
        f"- Authenticated account: {auth_user}",
        f"- Matched posts: {len(posts)}",
        "",
    ]

    for post in posts:
        if not isinstance(post, dict):
            continue

        author = post.get("author") if isinstance(post.get("author"), dict) else {}
        metrics = post.get("metrics") if isinstance(post.get("metrics"), dict) else {}
        timestamp = (
            post.get("createdAtISO")
            or post.get("createdAtLocal")
            or post.get("createdAt")
            or "Unknown time"
        )
        screen_name = author.get("screenName") or "unknown"
        tweet_id = post.get("id", "")
        tweet_url = (
            f"https://x.com/{screen_name}/status/{tweet_id}"
            if tweet_id
            else ""
        )

        lines.append(f"### {timestamp} - @{screen_name}")
        lines.append(str(post.get("text", "")).strip() or "(No text)")
        lines.append(
            "Metrics: likes={likes}, retweets={retweets}, replies={replies}, views={views}".format(
                likes=metrics.get("likes", 0),
                retweets=metrics.get("retweets", 0),
                replies=metrics.get("replies", 0),
                views=metrics.get("views", 0),
            )
        )
        if tweet_url:
            lines.append(f"Link: {tweet_url}")
        lines.append("")

    return "\n".join(lines).strip()


def _fallback_social_report(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    query: str,
    reason: str,
) -> str:
    fallback_news = _fetch_news_fallback(ticker, start_date, end_date)
    return (
        f"## X/Twitter Posts unavailable for {ticker}\n\n"
        f"Direct X/Twitter data is unavailable and the sentiment analysis must fall back to company news.\n"
        f"Reason: {reason}\n"
        f"Query: `{query}`\n"
        f"Date range: {start_date} to {end_date}\n\n"
        f"### News Proxy Fallback\n"
        f"{fallback_news}"
    )


def _fetch_news_fallback(ticker: str, start_date: str, end_date: str) -> str:
    try:
        from tradingagents.dataflows.interface import route_to_vendor

        return route_to_vendor("get_news", ticker, start_date, end_date)
    except Exception as exc:
        return f"Fallback news fetch failed: {exc}"
