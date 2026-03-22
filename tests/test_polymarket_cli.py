import copy
import json
import subprocess
from datetime import date
from pathlib import Path

import pytest
from langgraph.prebuilt import ToolNode

from cli.main import save_report_to_disk
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.config import get_config, set_config
from tradingagents.dataflows import polymarket_cli as pm
from tradingagents.agents.managers.polymarket_reviewer import create_polymarket_reviewer
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.setup import GraphSetup
from tradingagents.graph.trading_graph import TradingAgentsGraph


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "polymarket"


@pytest.fixture(autouse=True)
def restore_config():
    original = get_config()
    try:
        yield
    finally:
        set_config(original)


def _load_fixture(name: str):
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _make_config(tmp_path: Path) -> dict:
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["project_dir"] = str(tmp_path)
    config["data_cache_dir"] = str(tmp_path / "data_cache")
    config["data_vendors"] = dict(DEFAULT_CONFIG["data_vendors"])
    config["tool_vendors"] = dict(DEFAULT_CONFIG["tool_vendors"])
    config["polymarket_enabled"] = True
    config["polymarket_mode"] = "read_only"
    config["polymarket_historical_mode"] = "guarded"
    config["polymarket_live_window_days"] = 2
    config["polymarket_cli_path"] = "polymarket"
    config["polymarket_query_overrides"] = {
        "AAPL": ["Apple services revenue", "Apple Vision Pro demand"],
    }
    return config


def test_run_polymarket_json_uses_o_json_and_cache(monkeypatch, tmp_path):
    config = _make_config(tmp_path)
    set_config(config)

    calls = []
    payload = _load_fixture("markets_search_company.json")

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(pm.subprocess, "run", fake_run)

    first = pm._run_polymarket_json(["markets", "search", "AAPL", "--limit", "2"])
    second = pm._run_polymarket_json(["markets", "search", "AAPL", "--limit", "2"])

    assert first == payload
    assert second == payload
    assert len(calls) == 1
    assert calls[0][:3] == ["polymarket", "-o", "json"]


def test_run_polymarket_json_expired_cache_reexecutes(monkeypatch, tmp_path):
    config = _make_config(tmp_path)
    set_config(config)

    key_parts = ["polymarket", "-o", "json", "markets", "search", "AAPL", "--limit", "2"]
    cache_path = pm._cache_path_for_key(key_parts)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"cached_at": 0, "data": {"stale": True}}, ensure_ascii=True),
        encoding="utf-8",
    )

    payload = _load_fixture("markets_search_company.json")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(pm.subprocess, "run", fake_run)
    monkeypatch.setattr(pm.time, "time", lambda: pm._CACHE_TTL_SECONDS + 1000)

    result = pm._run_polymarket_json(["markets", "search", "AAPL", "--limit", "2"])

    assert result == payload
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("side_effect", "expected"),
    [
        (
            subprocess.TimeoutExpired(cmd=["polymarket"], timeout=20),
            "timed out",
        ),
        (
            FileNotFoundError(),
            "not found",
        ),
    ],
)
def test_run_polymarket_json_handles_cli_failures(monkeypatch, tmp_path, side_effect, expected):
    config = _make_config(tmp_path)
    set_config(config)

    def fake_run(*args, **kwargs):
        raise side_effect

    monkeypatch.setattr(pm.subprocess, "run", fake_run)

    result = pm._run_polymarket_json(["markets", "search", "AAPL", "--limit", "2"])

    assert result["ok"] is False
    assert expected in result["error"]


def test_run_polymarket_json_handles_malformed_json(monkeypatch, tmp_path):
    config = _make_config(tmp_path)
    set_config(config)

    monkeypatch.setattr(
        pm.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="{bad json",
            stderr="",
        ),
    )

    result = pm._run_polymarket_json(["markets", "search", "AAPL", "--limit", "2"])

    assert result["ok"] is False
    assert "malformed JSON" in result["error"]


def test_company_context_historical_guard_skips_subprocess(monkeypatch, tmp_path):
    config = _make_config(tmp_path)
    set_config(config)
    monkeypatch.setattr(pm, "_today_local", lambda: date(2026, 3, 21))

    def fail_run(*args, **kwargs):
        raise AssertionError("subprocess should not be called for guarded history")

    monkeypatch.setattr(pm.subprocess, "run", fail_run)

    report = pm.get_polymarket_company_context("AAPL", "Apple", "2026-03-10")

    assert "guarded" in report
    assert "temporal leakage" in report


def test_company_context_disabled_skips_subprocess(monkeypatch, tmp_path):
    config = _make_config(tmp_path)
    config["polymarket_enabled"] = False
    set_config(config)

    def fail_run(*args, **kwargs):
        raise AssertionError("subprocess should not be called when disabled")

    monkeypatch.setattr(pm.subprocess, "run", fail_run)

    report = pm.get_polymarket_company_context("AAPL", "Apple", "2026-03-21")

    assert "Polymarket context is unavailable" in report
    assert "disabled" in report


def test_company_context_formats_markdown(monkeypatch, tmp_path):
    config = _make_config(tmp_path)
    set_config(config)
    monkeypatch.setattr(pm, "_today_local", lambda: date(2026, 3, 21))

    markets = _load_fixture("markets_search_company.json")
    market_details = _load_fixture("market_get.json")
    event_details = _load_fixture("event_get.json")
    comments = _load_fixture("comments_list.json")
    midpoint = _load_fixture("midpoint.json")
    spread = _load_fixture("spread.json")
    book = _load_fixture("book.json")
    price_history = _load_fixture("price_history.json")
    open_interest = _load_fixture("open_interest.json")
    seen_queries = []

    def fake_search(query, limit):
        seen_queries.append(query)
        return markets

    monkeypatch.setattr(pm, "_search_markets", fake_search)
    monkeypatch.setattr(pm, "_get_market", lambda market_id: market_details | {"id": str(market_id)})
    monkeypatch.setattr(pm, "_get_event", lambda event_id: event_details | {"id": str(event_id)})
    monkeypatch.setattr(pm, "_get_comments", lambda *args, **kwargs: comments)
    monkeypatch.setattr(pm, "_get_midpoint", lambda token_id: midpoint)
    monkeypatch.setattr(pm, "_get_spread", lambda token_id: spread)
    monkeypatch.setattr(pm, "_get_book", lambda token_id: book)
    monkeypatch.setattr(pm, "_get_price_history", lambda token_id, interval, fidelity: price_history)
    monkeypatch.setattr(pm, "_get_open_interest", lambda condition_id: open_interest)

    report = pm.get_polymarket_company_context("AAPL", "Apple", "2026-03-21")

    assert "## Polymarket Company Context for AAPL" in report
    assert "### Executive summary" in report
    assert "### Market table" in report
    assert "### Bullish catalysts" in report
    assert "### Bearish catalysts" in report
    assert "### Watch items" in report
    assert "### Geopolitical linkage" in report
    assert "Will Apple beat earnings this quarter?" in report
    assert any(query == "AAPL" for query in seen_queries)
    assert any(query == "Apple earnings" for query in seen_queries)


@pytest.mark.parametrize(
    ("func_name", "args", "title"),
    [
        ("get_polymarket_macro_context", ("Apple", "2026-03-21"), "## Polymarket Macro Context for Apple"),
        (
            "get_polymarket_geopolitical_context",
            ("AAPL", "Apple", "2026-03-21"),
            "## Polymarket Geopolitical Context for AAPL",
        ),
    ],
)
def test_macro_and_geopolitical_contexts_format_markdown(
    monkeypatch,
    tmp_path,
    func_name,
    args,
    title,
):
    config = _make_config(tmp_path)
    set_config(config)
    monkeypatch.setattr(pm, "_today_local", lambda: date(2026, 3, 21))

    event_list = _load_fixture("events_list_macro.json")
    event_details = _load_fixture("event_get.json")
    comments = _load_fixture("comments_list.json")
    midpoint = _load_fixture("midpoint.json")
    spread = _load_fixture("spread.json")
    book = _load_fixture("book.json")
    price_history = _load_fixture("price_history.json")
    open_interest = _load_fixture("open_interest.json")

    monkeypatch.setattr(pm, "_search_markets", lambda *args, **kwargs: [])
    monkeypatch.setattr(pm, "_list_events_by_tag", lambda tag, limit: event_list)
    monkeypatch.setattr(pm, "_get_market", lambda market_id: event_details["markets"][0] | {"id": str(market_id)})
    monkeypatch.setattr(pm, "_get_event", lambda event_id: event_details | {"id": str(event_id)})
    monkeypatch.setattr(pm, "_get_comments", lambda *args, **kwargs: comments)
    monkeypatch.setattr(pm, "_get_midpoint", lambda token_id: midpoint)
    monkeypatch.setattr(pm, "_get_spread", lambda token_id: spread)
    monkeypatch.setattr(pm, "_get_book", lambda token_id: book)
    monkeypatch.setattr(pm, "_get_price_history", lambda token_id, interval, fidelity: price_history)
    monkeypatch.setattr(pm, "_get_open_interest", lambda condition_id: open_interest)

    report = getattr(pm, func_name)(*args)

    assert title in report
    assert "### Executive summary" in report
    assert "### Market table" in report
    assert "### Geopolitical linkage" in report


def test_unavailable_when_cli_errors(monkeypatch, tmp_path):
    config = _make_config(tmp_path)
    set_config(config)
    monkeypatch.setattr(pm, "_today_local", lambda: date(2026, 3, 21))
    monkeypatch.setattr(pm, "_search_markets", lambda *args, **kwargs: _load_fixture("error.json") | {"ok": False})

    report = pm.get_polymarket_company_context("AAPL", "Apple", "2026-03-21")

    assert "unavailable" in report
    assert "Polymarket CLI data was unavailable: synthetic polymarket error" in report


def test_tool_nodes_include_polymarket_tools():
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    tool_nodes = TradingAgentsGraph._create_tool_nodes(graph)

    assert set(tool_nodes["market"].tools_by_name) == {
        "get_stock_data",
        "get_indicators",
    }
    assert set(tool_nodes["social"].tools_by_name) == {
        "get_social_posts",
    }
    assert set(tool_nodes["news"].tools_by_name) == {
        "get_news",
        "get_global_news",
        "get_insider_transactions",
        "get_polymarket_macro_context",
        "get_polymarket_geopolitical_context",
    }


def test_graph_topology_unchanged():
    graph_instance = TradingAgentsGraph.__new__(TradingAgentsGraph)
    tool_nodes = TradingAgentsGraph._create_tool_nodes(graph_instance)

    setup = GraphSetup(
        quick_thinking_llm=object(),
        deep_thinking_llm=object(),
        tool_nodes=tool_nodes,
        bull_memory=None,
        bear_memory=None,
        trader_memory=None,
        invest_judge_memory=None,
        risk_manager_memory=None,
        conditional_logic=ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1),
    )
    compiled = setup.setup_graph(["market", "social", "news", "fundamentals"])
    graph = compiled.get_graph()

    edges = {(edge.source, edge.target, bool(edge.conditional)) for edge in graph.edges}
    expected = {
        ("__start__", "Market Analyst", False),
        ("Market Analyst", "Msg Clear Market", True),
        ("Market Analyst", "tools_market", True),
        ("tools_market", "Market Analyst", False),
        ("Msg Clear Market", "Social Analyst", False),
        ("Social Analyst", "Msg Clear Social", True),
        ("Social Analyst", "tools_social", True),
        ("tools_social", "Social Analyst", False),
        ("Msg Clear Social", "News Analyst", False),
        ("News Analyst", "Msg Clear News", True),
        ("News Analyst", "tools_news", True),
        ("tools_news", "News Analyst", False),
        ("Msg Clear News", "Fundamentals Analyst", False),
        ("Fundamentals Analyst", "Msg Clear Fundamentals", True),
        ("Fundamentals Analyst", "tools_fundamentals", True),
        ("tools_fundamentals", "Fundamentals Analyst", False),
        ("Msg Clear Fundamentals", "Bull Researcher", False),
        ("Bull Researcher", "Bear Researcher", True),
        ("Bull Researcher", "Research Manager", True),
        ("Bear Researcher", "Bull Researcher", True),
        ("Bear Researcher", "Research Manager", True),
        ("Research Manager", "Trader", False),
        ("Trader", "Aggressive Analyst", False),
        ("Aggressive Analyst", "Conservative Analyst", True),
        ("Aggressive Analyst", "Risk Judge", True),
        ("Conservative Analyst", "Neutral Analyst", True),
        ("Conservative Analyst", "Risk Judge", True),
        ("Neutral Analyst", "Aggressive Analyst", True),
        ("Neutral Analyst", "Risk Judge", True),
        ("Risk Judge", "__end__", False),
    }

    expected.remove(("Research Manager", "Trader", False))
    expected.add(("Research Manager", "Polymarket Review", False))
    expected.add(("Polymarket Review", "Trader", False))

    assert edges == expected
    assert "Prediction Market Analyst" not in graph.nodes
    assert "Polymarket Review" in graph.nodes


def test_prompt_sources_include_polymarket_sections():
    market_source = Path("D:/TradingAgents/tradingagents/agents/analysts/market_analyst.py").read_text(encoding="utf-8")
    social_source = Path("D:/TradingAgents/tradingagents/agents/analysts/social_media_analyst.py").read_text(encoding="utf-8")
    news_source = Path("D:/TradingAgents/tradingagents/agents/analysts/news_analyst.py").read_text(encoding="utf-8")
    research_source = Path("D:/TradingAgents/tradingagents/agents/managers/research_manager.py").read_text(encoding="utf-8")
    trader_source = Path("D:/TradingAgents/tradingagents/agents/trader/trader.py").read_text(encoding="utf-8")
    risk_source = Path("D:/TradingAgents/tradingagents/agents/managers/risk_manager.py").read_text(encoding="utf-8")

    assert "## Polymarket Event Surface" not in market_source
    assert "## Polymarket Crowd Narrative" not in social_source
    assert "## Polymarket Macro Reference" in news_source
    assert "## Polymarket Geopolitical Reference" in news_source
    assert "## Risk Warning" in news_source
    assert "event priors support Buy/Sell/Hold" not in research_source
    assert "secondary event-pricing check" in trader_source
    assert "supplementary event-pricing note" in risk_source


def test_polymarket_reviewer_supportive_note(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.agents.managers.polymarket_reviewer.route_to_vendor",
        lambda *args, **kwargs: (
            "## Polymarket Company Context for NVDA\n\n"
            "### Executive summary\n"
            "- Top event prior: Will Nvidia beat earnings? (midpoint 68%, quality high)\n"
            "- Event signal mix: 2 bullish, 0 bearish, 0 low-quality markets.\n"
        ),
    )

    reviewer = create_polymarket_reviewer()
    result = reviewer(
        {
            "company_of_interest": "NVDA",
            "trade_date": "2026-03-21",
            "investment_plan": "FINAL TRANSACTION PROPOSAL: **BUY**",
        }
    )

    assert "## Polymarket Review" in result["polymarket_report"]
    assert "- Conviction Impact: `supportive`" in result["polymarket_report"]
    assert "secondary event-pricing check" in result["polymarket_report"]


def test_polymarket_reviewer_guarded_note_is_neutral(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.agents.managers.polymarket_reviewer.route_to_vendor",
        lambda *args, **kwargs: (
            "## Polymarket Company Context for NVDA\n\n"
            "### Executive summary\n"
            "- Polymarket context is guarded: historical access is disabled to avoid temporal leakage.\n"
        ),
    )

    reviewer = create_polymarket_reviewer()
    result = reviewer(
        {
            "company_of_interest": "NVDA",
            "trade_date": "2026-03-10",
            "investment_plan": "FINAL TRANSACTION PROPOSAL: **BUY**",
        }
    )

    assert "- Status: `guarded`" in result["polymarket_report"]
    assert "- Conviction Impact: `neutral`" in result["polymarket_report"]


def test_save_report_to_disk_writes_polymarket_review(tmp_path):
    final_state = {
        "market_report": "",
        "sentiment_report": "",
        "news_report": "",
        "fundamentals_report": "",
        "investment_debate_state": {
            "bull_history": "",
            "bear_history": "",
            "judge_decision": "Research manager decision",
        },
        "polymarket_report": "## Polymarket Review\n\n- Status: `neutral`",
        "trader_investment_plan": "",
        "risk_debate_state": {},
    }

    report_path = save_report_to_disk(
        final_state=final_state,
        ticker="NVDA",
        save_path=tmp_path / "report",
        report_language="english",
    )

    polymarket_file = tmp_path / "report" / "2_research" / "polymarket.md"
    assert polymarket_file.exists()
    assert "Status" in polymarket_file.read_text(encoding="utf-8")
    assert "## Polymarket Review" in report_path.read_text(encoding="utf-8")
