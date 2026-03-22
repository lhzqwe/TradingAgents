import json
import subprocess
from pathlib import Path

import pytest

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.config import get_config, set_config
from tradingagents.dataflows.twitter_cli_social import get_social_posts_twitter_cli
from tradingagents.graph.trading_graph import TradingAgentsGraph


@pytest.fixture(autouse=True)
def restore_config():
    original = get_config()
    try:
        yield
    finally:
        set_config(original)


def _make_config(tmp_path: Path):
    repo_root = tmp_path / "repo"
    project_dir = repo_root / "tradingagents"
    project_dir.mkdir(parents=True, exist_ok=True)

    config = DEFAULT_CONFIG.copy()
    config["project_dir"] = str(project_dir)
    config["data_vendors"] = dict(DEFAULT_CONFIG["data_vendors"])
    config["tool_vendors"] = dict(DEFAULT_CONFIG["tool_vendors"])
    config["twitter_cli"] = dict(DEFAULT_CONFIG["twitter_cli"])
    return config, repo_root


def _write_fake_submodule(repo_root: Path):
    submodule = repo_root / "external" / "twitter-cli" / "twitter_cli"
    submodule.mkdir(parents=True, exist_ok=True)
    (submodule / "cli.py").write_text("def cli():\n    pass\n", encoding="utf-8")


def test_get_social_posts_formats_success(monkeypatch, tmp_path):
    config, repo_root = _make_config(tmp_path)
    _write_fake_submodule(repo_root)
    set_config(config)

    responses = [
        subprocess.CompletedProcess(
            args=["status"],
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "schema_version": "1",
                    "data": {"authenticated": True, "user": {"screenName": "tester"}},
                }
            ),
            stderr="",
        ),
        subprocess.CompletedProcess(
            args=["search"],
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "schema_version": "1",
                    "data": [
                        {
                            "id": "123",
                            "text": "AMD momentum is improving.",
                            "author": {"screenName": "markets"},
                            "metrics": {
                                "likes": 11,
                                "retweets": 4,
                                "replies": 2,
                                "views": 98,
                            },
                            "createdAtISO": "2026-03-21T08:00:00+00:00",
                        }
                    ],
                }
            ),
            stderr="",
        ),
    ]

    monkeypatch.setattr(
        "tradingagents.dataflows.twitter_cli_social._run_twitter_cli",
        lambda *args, **kwargs: responses.pop(0),
    )

    report = get_social_posts_twitter_cli("AMD", "2026-03-14", "2026-03-21")

    assert "## X/Twitter Posts for AMD" in report
    assert "- Query: `$AMD`" in report
    assert "- Authenticated account: @tester" in report
    assert "AMD momentum is improving." in report
    assert "likes=11, retweets=4, replies=2, views=98" in report
    assert "https://x.com/markets/status/123" in report


def test_get_social_posts_missing_submodule_soft_fallback(monkeypatch, tmp_path):
    config, _repo_root = _make_config(tmp_path)
    set_config(config)

    monkeypatch.setattr(
        "tradingagents.dataflows.twitter_cli_social._fetch_news_fallback",
        lambda ticker, start_date, end_date: "NEWS FALLBACK",
    )

    report = get_social_posts_twitter_cli("AMD", "2026-03-14", "2026-03-21")

    assert "Direct X/Twitter data is unavailable" in report
    assert "NEWS FALLBACK" in report


def test_get_social_posts_status_not_authenticated_falls_back(monkeypatch, tmp_path):
    config, repo_root = _make_config(tmp_path)
    _write_fake_submodule(repo_root)
    set_config(config)

    monkeypatch.setattr(
        "tradingagents.dataflows.twitter_cli_social._fetch_news_fallback",
        lambda ticker, start_date, end_date: "NEWS FALLBACK",
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.twitter_cli_social._run_twitter_cli",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["status"],
            returncode=1,
            stdout=json.dumps(
                {
                    "ok": False,
                    "schema_version": "1",
                    "error": {
                        "code": "not_authenticated",
                        "message": "Cookie expired",
                    },
                }
            ),
            stderr="",
        ),
    )

    report = get_social_posts_twitter_cli("AMD", "2026-03-14", "2026-03-21")

    assert "twitter-cli not_authenticated: Cookie expired" in report
    assert "NEWS FALLBACK" in report


@pytest.mark.parametrize(
    "search_response",
    [
        subprocess.CompletedProcess(args=["search"], returncode=0, stdout="{bad json", stderr=""),
        subprocess.CompletedProcess(args=["search"], returncode=2, stdout="", stderr="boom"),
        subprocess.CompletedProcess(
            args=["search"],
            returncode=0,
            stdout=json.dumps({"ok": True, "schema_version": "1", "data": []}),
            stderr="",
        ),
    ],
)
def test_get_social_posts_search_failures_fall_back(
    monkeypatch,
    tmp_path,
    search_response,
):
    config, repo_root = _make_config(tmp_path)
    _write_fake_submodule(repo_root)
    set_config(config)

    monkeypatch.setattr(
        "tradingagents.dataflows.twitter_cli_social._fetch_news_fallback",
        lambda ticker, start_date, end_date: "NEWS FALLBACK",
    )
    responses = [
        subprocess.CompletedProcess(
            args=["status"],
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "schema_version": "1",
                    "data": {"authenticated": True, "user": {"screenName": "tester"}},
                }
            ),
            stderr="",
        ),
        search_response,
    ]

    monkeypatch.setattr(
        "tradingagents.dataflows.twitter_cli_social._run_twitter_cli",
        lambda *args, **kwargs: responses.pop(0),
    )

    report = get_social_posts_twitter_cli("AMD", "2026-03-14", "2026-03-21")

    assert "Direct X/Twitter data is unavailable" in report
    assert "NEWS FALLBACK" in report


def test_get_social_posts_uses_query_override_and_inclusive_until(
    monkeypatch,
    tmp_path,
):
    config, repo_root = _make_config(tmp_path)
    _write_fake_submodule(repo_root)
    config["twitter_cli"]["query_overrides"] = {"AMD": "Advanced Micro Devices"}
    set_config(config)

    calls = []
    responses = [
        subprocess.CompletedProcess(
            args=["status"],
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "schema_version": "1",
                    "data": {"authenticated": True, "user": {"screenName": "tester"}},
                }
            ),
            stderr="",
        ),
        subprocess.CompletedProcess(
            args=["search"],
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "schema_version": "1",
                    "data": [
                        {
                            "id": "123",
                            "text": "AMD post",
                            "author": {"screenName": "markets"},
                            "metrics": {},
                            "createdAtISO": "2026-03-21T08:00:00+00:00",
                        }
                    ],
                }
            ),
            stderr="",
        ),
    ]

    def fake_run(args, **kwargs):
        calls.append(args)
        return responses.pop(0)

    monkeypatch.setattr(
        "tradingagents.dataflows.twitter_cli_social._run_twitter_cli",
        fake_run,
    )

    get_social_posts_twitter_cli("AMD", "2026-03-14", "2026-03-21")

    search_args = calls[1]
    assert "Advanced Micro Devices" in search_args
    assert "--until" in search_args
    assert search_args[search_args.index("--until") + 1] == "2026-03-22"


def test_social_tool_node_exposes_social_and_polymarket_tools():
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    tool_nodes = TradingAgentsGraph._create_tool_nodes(graph)

    assert set(tool_nodes["social"].tools_by_name) == {
        "get_social_posts",
    }
    assert set(tool_nodes["market"].tools_by_name) == {
        "get_stock_data",
        "get_indicators",
    }
    assert "get_news" in tool_nodes["news"].tools_by_name
    assert "get_global_news" in tool_nodes["news"].tools_by_name
    assert "get_polymarket_macro_context" in tool_nodes["news"].tools_by_name
    assert "get_polymarket_geopolitical_context" in tool_nodes["news"].tools_by_name
