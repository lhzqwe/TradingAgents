import copy

import pandas as pd
import pytest

from cli.main import build_non_interactive_selections
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.config import (
    get_config,
    set_config,
    clear_runtime_context,
    get_runtime_context,
)
from tradingagents.dataflows.interface import route_to_vendor, VENDOR_METHODS
from tradingagents.dataflows.market_symbol import (
    resolve_market_and_symbols,
    MARKET_AUTO,
    MARKET_HK,
    MARKET_US,
)
from tradingagents.dataflows.tigeropen_common import TigerOpenConfigError
from tradingagents.dataflows.tigeropen_common import get_tigeropen_settings
from tradingagents.dataflows.tigeropen_stock import get_stock_data_tigeropen
from tradingagents.graph.propagation import Propagator


@pytest.fixture(autouse=True)
def restore_state():
    original_config = get_config()
    original_methods = {method: vendors.copy() for method, vendors in VENDOR_METHODS.items()}
    original_context = get_runtime_context()
    try:
        yield
    finally:
        set_config(original_config)
        clear_runtime_context()
        if original_context:
            from tradingagents.dataflows.config import set_runtime_context

            set_runtime_context(original_context)
        for method, vendors in original_methods.items():
            VENDOR_METHODS[method].clear()
            VENDOR_METHODS[method].update(vendors)


def _make_config():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["data_vendors"] = dict(DEFAULT_CONFIG["data_vendors"])
    config["tool_vendors"] = dict(DEFAULT_CONFIG["tool_vendors"])
    config["market_routing"] = dict(DEFAULT_CONFIG["market_routing"])
    config["tigeropen"] = dict(DEFAULT_CONFIG["tigeropen"])
    return config


@pytest.mark.parametrize(
    ("raw_symbol", "expected_tiger", "expected_yfinance"),
    [
        ("0700.HK", "00700", "0700.HK"),
        ("00700.HK", "00700", "0700.HK"),
        ("HK.00700", "00700", "0700.HK"),
        ("700", "00700", "0700.HK"),
    ],
)
def test_resolve_market_and_symbols_hk_variants(
    raw_symbol,
    expected_tiger,
    expected_yfinance,
):
    resolved = resolve_market_and_symbols(raw_symbol)

    assert resolved.market == MARKET_HK
    assert resolved.tiger_symbol == expected_tiger
    assert resolved.yfinance_symbol == expected_yfinance


def test_resolve_market_and_symbols_us_defaults():
    resolved = resolve_market_and_symbols("AAPL")

    assert resolved.market == MARKET_US
    assert resolved.tiger_symbol == "AAPL"
    assert resolved.yfinance_symbol == "AAPL"


def test_build_non_interactive_selections_normalizes_market():
    selections = build_non_interactive_selections(
        ticker="0700.hk",
        market="hk",
        analysis_date="2026-03-20",
        analysts=["market"],
        all_analysts=False,
        research_depth=1,
        llm_provider="openai",
        backend_url=None,
        shallow_thinker=None,
        deep_thinker=None,
        google_thinking_level=None,
        openai_reasoning_effort=None,
        auth_profile_id=None,
        report_language="english",
    )

    assert selections["ticker"] == "0700.HK"
    assert selections["market"] == MARKET_HK


def test_propagator_initial_state_sets_market_and_runtime_context():
    state = Propagator().create_initial_state("0700.HK", "2026-03-20", market="HK")

    assert state["market"] == MARKET_HK
    assert get_runtime_context()["market"] == MARKET_HK
    assert get_runtime_context()["trade_date"] == "2026-03-20"


def test_route_to_vendor_hk_stock_prefers_tiger(monkeypatch):
    config = _make_config()
    config["data_vendors"]["core_stock_apis"] = "yfinance"
    set_config(config)

    captured = {}

    def fake_tiger(symbol, start_date, end_date):
        captured["symbol"] = symbol
        return "TIGER"

    def fake_yfinance(symbol, start_date, end_date):
        raise AssertionError("Tiger should be tried first for HK stock data.")

    monkeypatch.setitem(VENDOR_METHODS["get_stock_data"], "tigeropen", fake_tiger)
    monkeypatch.setitem(VENDOR_METHODS["get_stock_data"], "yfinance", fake_yfinance)

    from tradingagents.dataflows.config import set_runtime_context

    set_runtime_context({"market": MARKET_HK})
    result = route_to_vendor("get_stock_data", "0700.HK", "2026-03-01", "2026-03-05")

    assert result == "TIGER"
    assert captured["symbol"] == "00700"


def test_route_to_vendor_hk_news_uses_yfinance_compatible_symbol(monkeypatch):
    config = _make_config()
    config["data_vendors"]["news_data"] = "yfinance"
    set_config(config)

    captured = {}

    def fake_news(symbol, start_date, end_date):
        captured["symbol"] = symbol
        return "NEWS"

    monkeypatch.setitem(VENDOR_METHODS["get_news"], "yfinance", fake_news)

    from tradingagents.dataflows.config import set_runtime_context

    set_runtime_context({"market": MARKET_HK})
    result = route_to_vendor("get_news", "700", "2026-03-01", "2026-03-05")

    assert result == "NEWS"
    assert captured["symbol"] == "0700.HK"


def test_route_to_vendor_tiger_failure_falls_back_to_yfinance(monkeypatch):
    config = _make_config()
    config["data_vendors"]["core_stock_apis"] = "yfinance"
    set_config(config)

    def fake_tiger(symbol, start_date, end_date):
        raise TigerOpenConfigError("missing Tiger credentials")

    def fake_yfinance(symbol, start_date, end_date):
        return symbol

    monkeypatch.setitem(VENDOR_METHODS["get_stock_data"], "tigeropen", fake_tiger)
    monkeypatch.setitem(VENDOR_METHODS["get_stock_data"], "yfinance", fake_yfinance)

    from tradingagents.dataflows.config import set_runtime_context

    set_runtime_context({"market": MARKET_HK})
    result = route_to_vendor("get_stock_data", "700", "2026-03-01", "2026-03-05")

    assert result == "0700.HK"


def test_route_to_vendor_tiger_no_data_falls_back_to_yfinance(monkeypatch):
    config = _make_config()
    config["data_vendors"]["core_stock_apis"] = "yfinance"
    set_config(config)

    def fake_tiger(symbol, start_date, end_date):
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

    def fake_yfinance(symbol, start_date, end_date):
        return symbol

    monkeypatch.setitem(VENDOR_METHODS["get_stock_data"], "tigeropen", fake_tiger)
    monkeypatch.setitem(VENDOR_METHODS["get_stock_data"], "yfinance", fake_yfinance)

    from tradingagents.dataflows.config import set_runtime_context

    set_runtime_context({"market": MARKET_HK})
    result = route_to_vendor("get_stock_data", "700", "2026-03-01", "2026-03-05")

    assert result == "0700.HK"


def test_route_to_vendor_cashflow_no_data_falls_back_to_alpha_vantage(monkeypatch):
    config = _make_config()
    config["data_vendors"]["fundamental_data"] = "yfinance"
    set_config(config)

    captured = {}

    def fake_yfinance(symbol, freq="quarterly", curr_date=None):
        captured["yfinance_symbol"] = symbol
        return f"No cash flow data found for symbol '{symbol}'"

    def fake_alpha(symbol, freq="quarterly", curr_date=None):
        captured["alpha_symbol"] = symbol
        return "ALPHA_CASHFLOW"

    monkeypatch.setitem(VENDOR_METHODS["get_cashflow"], "yfinance", fake_yfinance)
    monkeypatch.setitem(VENDOR_METHODS["get_cashflow"], "alpha_vantage", fake_alpha)

    from tradingagents.dataflows.config import set_runtime_context

    set_runtime_context({"market": MARKET_HK})
    result = route_to_vendor("get_cashflow", "700", "quarterly", "2026-03-20")

    assert result == "ALPHA_CASHFLOW"
    assert captured["yfinance_symbol"] == "0700.HK"
    assert captured["alpha_symbol"] == "0700.HK"


def test_route_to_vendor_news_no_data_falls_back_to_next_vendor(monkeypatch):
    config = _make_config()
    config["data_vendors"]["news_data"] = "yfinance"
    set_config(config)

    def fake_yfinance(symbol, start_date, end_date):
        return f"No news found for {symbol}"

    def fake_alpha(symbol, start_date, end_date):
        return "ALPHA_NEWS"

    monkeypatch.setitem(VENDOR_METHODS["get_news"], "yfinance", fake_yfinance)
    monkeypatch.setitem(VENDOR_METHODS["get_news"], "alpha_vantage", fake_alpha)

    from tradingagents.dataflows.config import set_runtime_context

    set_runtime_context({"market": MARKET_HK})
    result = route_to_vendor("get_news", "700", "2026-03-01", "2026-03-05")

    assert result == "ALPHA_NEWS"


def test_route_to_vendor_returns_last_no_data_result_when_all_vendors_empty(monkeypatch):
    config = _make_config()
    config["data_vendors"]["fundamental_data"] = "yfinance"
    set_config(config)

    expected = "No cash flow data found for symbol '0700.HK' via alpha"

    def fake_yfinance(symbol, freq="quarterly", curr_date=None):
        return f"No cash flow data found for symbol '{symbol}'"

    def fake_alpha(symbol, freq="quarterly", curr_date=None):
        return expected

    monkeypatch.setitem(VENDOR_METHODS["get_cashflow"], "yfinance", fake_yfinance)
    monkeypatch.setitem(VENDOR_METHODS["get_cashflow"], "alpha_vantage", fake_alpha)

    from tradingagents.dataflows.config import set_runtime_context

    set_runtime_context({"market": MARKET_HK})
    result = route_to_vendor("get_cashflow", "700", "quarterly", "2026-03-20")

    assert result == expected


def test_route_to_vendor_non_no_data_error_is_returned_immediately(monkeypatch):
    config = _make_config()
    config["data_vendors"]["fundamental_data"] = "yfinance"
    set_config(config)

    def fake_yfinance(symbol, freq="quarterly", curr_date=None):
        return f"Error retrieving cash flow for {symbol}: upstream unavailable"

    def fake_alpha(symbol, freq="quarterly", curr_date=None):
        raise AssertionError("Non no-data errors should not trigger fallback.")

    monkeypatch.setitem(VENDOR_METHODS["get_cashflow"], "yfinance", fake_yfinance)
    monkeypatch.setitem(VENDOR_METHODS["get_cashflow"], "alpha_vantage", fake_alpha)

    from tradingagents.dataflows.config import set_runtime_context

    set_runtime_context({"market": MARKET_HK})
    result = route_to_vendor("get_cashflow", "700", "quarterly", "2026-03-20")

    assert result == "Error retrieving cash flow for 0700.HK: upstream unavailable"


def test_route_to_vendor_returns_last_no_data_when_alpha_key_is_missing(monkeypatch):
    config = _make_config()
    config["data_vendors"]["fundamental_data"] = "yfinance"
    set_config(config)

    expected = "No cash flow data found for symbol '0700.HK'"

    def fake_yfinance(symbol, freq="quarterly", curr_date=None):
        return expected

    def fake_alpha(symbol, freq="quarterly", curr_date=None):
        raise ValueError("ALPHA_VANTAGE_API_KEY environment variable is not set.")

    monkeypatch.setitem(VENDOR_METHODS["get_cashflow"], "yfinance", fake_yfinance)
    monkeypatch.setitem(VENDOR_METHODS["get_cashflow"], "alpha_vantage", fake_alpha)

    from tradingagents.dataflows.config import set_runtime_context

    set_runtime_context({"market": MARKET_HK})
    result = route_to_vendor("get_cashflow", "700", "quarterly", "2026-03-20")

    assert result == expected


def test_route_to_vendor_respects_auto_detect_toggle(monkeypatch):
    config = _make_config()
    config["data_vendors"]["core_stock_apis"] = "yfinance"
    config["market_routing"]["auto_detect_hk"] = False
    set_config(config)

    def fake_tiger(symbol, start_date, end_date):
        raise AssertionError("AUTO HK detection should be disabled.")

    def fake_yfinance(symbol, start_date, end_date):
        return symbol

    monkeypatch.setitem(VENDOR_METHODS["get_stock_data"], "tigeropen", fake_tiger)
    monkeypatch.setitem(VENDOR_METHODS["get_stock_data"], "yfinance", fake_yfinance)

    from tradingagents.dataflows.config import set_runtime_context

    set_runtime_context({"market": MARKET_AUTO})
    result = route_to_vendor("get_stock_data", "700", "2026-03-01", "2026-03-05")

    assert result == "700"


def test_get_tigeropen_settings_uses_default_state_dir_props(monkeypatch, tmp_path):
    config = _make_config()
    config["tigeropen"]["props_path"] = None
    set_config(config)

    state_dir = tmp_path / ".tradingagents"
    tiger_dir = state_dir / "tiger"
    tiger_dir.mkdir(parents=True)
    props_file = tiger_dir / "tiger_openapi_config.properties"
    props_file.write_text("tiger_id=test\n", encoding="utf-8")

    monkeypatch.delenv("TIGER_CONFIG_PATH", raising=False)
    monkeypatch.setenv("TRADINGAGENTS_STATE_DIR", str(state_dir))

    settings = get_tigeropen_settings()

    assert settings["props_path"] == str(props_file)


def test_get_stock_data_tigeropen_formats_output(monkeypatch):
    class FakeQuoteClient:
        def get_bars_by_page(self, **kwargs):
            return pd.DataFrame(
                [
                    {
                        "time": 1772409600000,
                        "open": 100.1,
                        "high": 101.2,
                        "low": 99.8,
                        "close": 100.9,
                        "volume": 1200,
                        "amount": 5000,
                        "turnover_rate": 0.7,
                        "ttm_pe": 18.1,
                    }
                ]
            )

    monkeypatch.setattr(
        "tradingagents.dataflows.tigeropen_stock.get_tiger_quote_client",
        lambda: FakeQuoteClient(),
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.tigeropen_stock.get_tigeropen_settings",
        lambda: {
            "with_fundamental": True,
            "right": "BR",
            "lang": "en_US",
            "indicator_history_years": 15,
        },
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.tigeropen_stock.resolve_tiger_symbol",
        lambda symbol: symbol,
    )

    report = get_stock_data_tigeropen("00700", "2026-03-01", "2026-03-02")

    assert "# Data source: tigeropen" in report
    assert "TTM PE" in report
    assert "100.9" in report


def test_get_indicator_tigeropen_falls_back_to_runtime_trade_date(monkeypatch):
    from tradingagents.dataflows.config import set_runtime_context
    from tradingagents.dataflows.tigeropen_stock import get_indicator_tigeropen

    monkeypatch.setattr(
        "tradingagents.dataflows.tigeropen_stock._get_tiger_stock_stats_bulk",
        lambda symbol, indicator, curr_date: {
            "2026-03-20": "1.23",
            "2026-03-19": "0.99",
        },
    )

    set_runtime_context({"market": MARKET_HK, "trade_date": "2026-03-20"})
    report = get_indicator_tigeropen("00700", "macds", "0700", 1)

    assert "2026-03-20: 1.23" in report
