from typing import Annotated

# Import from vendor-specific modules
from .y_finance import (
    get_YFin_data_online,
    get_stock_stats_indicators_window,
    get_fundamentals as get_yfinance_fundamentals,
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
)
from .twitter_cli_social import get_social_posts_twitter_cli
from .polymarket_cli import (
    get_polymarket_company_context as get_polymarket_company_context_cli,
    get_polymarket_macro_context as get_polymarket_macro_context_cli,
    get_polymarket_geopolitical_context as get_polymarket_geopolitical_context_cli,
)
from .yfinance_news import get_news_yfinance, get_global_news_yfinance
from .tigeropen_stock import get_stock_data_tigeropen, get_indicator_tigeropen
from .alpha_vantage import (
    get_stock as get_alpha_vantage_stock,
    get_indicator as get_alpha_vantage_indicator,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_income_statement as get_alpha_vantage_income_statement,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_global_news as get_alpha_vantage_global_news,
)
from .alpha_vantage_common import AlphaVantageRateLimitError
from .tigeropen_common import TigerOpenRecoverableError
from .market_symbol import MARKET_HK, resolve_market_and_symbols
from .config import get_runtime_context

# Configuration and routing logic
from .config import get_config

_NO_DATA_PREFIXES = {
    "get_stock_data": (
        "No data found for symbol ",
    ),
    "get_fundamentals": (
        "No fundamentals data found for symbol ",
    ),
    "get_balance_sheet": (
        "No balance sheet data found for symbol ",
    ),
    "get_cashflow": (
        "No cash flow data found for symbol ",
    ),
    "get_income_statement": (
        "No income statement data found for symbol ",
    ),
    "get_insider_transactions": (
        "No insider transactions data found for symbol ",
    ),
    "get_news": (
        "No news found for ",
    ),
    "get_global_news": (
        "No global news found for ",
    ),
}

_NO_DATA_SUBSTRINGS = {
    "get_indicators": (
        "No data available for the specified date range.",
    ),
}

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "social_data": {
        "description": "Social media posts",
        "tools": [
            "get_social_posts"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    },
    "prediction_market_data": {
        "description": "Prediction market context",
        "tools": [
            "get_polymarket_company_context",
            "get_polymarket_macro_context",
            "get_polymarket_geopolitical_context",
        ]
    }
}

VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
    "tigeropen",
    "twitter_cli",
    "polymarket_cli",
]

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
        "tigeropen": get_stock_data_tigeropen,
    },
    # technical_indicators
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
        "tigeropen": get_indicator_tigeropen,
    },
    # fundamental_data
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
    },
    # social_data
    "get_social_posts": {
        "twitter_cli": get_social_posts_twitter_cli,
    },
    # prediction_market_data
    "get_polymarket_company_context": {
        "polymarket_cli": get_polymarket_company_context_cli,
    },
    "get_polymarket_macro_context": {
        "polymarket_cli": get_polymarket_macro_context_cli,
    },
    "get_polymarket_geopolitical_context": {
        "polymarket_cli": get_polymarket_geopolitical_context_cli,
    },
    # news_data
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
    },
    "get_global_news": {
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support."""
    category = get_category_for_method(method)
    market_context = get_runtime_context().get("market")
    primary_vendors, resolved_symbol = _build_vendor_chain(
        method,
        category,
        market_context,
        args,
    )

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Build fallback chain: primary vendors first, then remaining available vendors
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    last_no_data_result = None
    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl
        normalized_args = _normalize_args_for_vendor(
            method,
            vendor,
            args,
            resolved_symbol,
        )

        try:
            result = impl_func(*normalized_args, **kwargs)
        except Exception as exc:
            if _is_recoverable_vendor_exception(vendor, exc):
                continue
            raise
        if _is_no_data_result(method, result):
            last_no_data_result = result
            continue
        return result

    if last_no_data_result is not None:
        return last_no_data_result
    raise RuntimeError(f"No available vendor for '{method}'")


def _build_vendor_chain(
    method: str,
    category: str,
    market_context: str | None,
    args: tuple,
) -> tuple[list[str], object | None]:
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(",") if v.strip()]
    resolved_symbol = None

    if _method_uses_symbol(method) and args:
        config = get_config()
        market_routing = config.get("market_routing", {})
        auto_detect_hk = market_routing.get("auto_detect_hk", True)
        resolver_market = market_context
        if not auto_detect_hk and (market_context is None or market_context == "AUTO"):
            resolver_market = "US"

        resolved_symbol = resolve_market_and_symbols(args[0], resolver_market)
        if resolved_symbol.market == MARKET_HK:
            if method == "get_stock_data":
                hk_vendor = market_routing.get("hk_stock_vendor")
                if hk_vendor:
                    primary_vendors.insert(0, hk_vendor)
            elif method == "get_indicators":
                hk_vendor = market_routing.get("hk_indicator_vendor")
                if hk_vendor:
                    primary_vendors.insert(0, hk_vendor)

    deduped_vendors = []
    for vendor in primary_vendors:
        if vendor not in deduped_vendors:
            deduped_vendors.append(vendor)

    return deduped_vendors, resolved_symbol


def _normalize_args_for_vendor(method: str, vendor: str, args: tuple, resolved_symbol) -> tuple:
    if not _method_uses_symbol(method) or not args or resolved_symbol is None:
        return args

    normalized_args = list(args)
    normalized_args[0] = _get_vendor_symbol(vendor, resolved_symbol)
    return tuple(normalized_args)


def _get_vendor_symbol(vendor: str, resolved_symbol) -> str:
    if vendor == "tigeropen":
        return resolved_symbol.tiger_symbol
    return resolved_symbol.yfinance_symbol


def _method_uses_symbol(method: str) -> bool:
    return method in {
        "get_stock_data",
        "get_indicators",
        "get_fundamentals",
        "get_balance_sheet",
        "get_cashflow",
        "get_income_statement",
        "get_social_posts",
        "get_news",
        "get_insider_transactions",
    }


def _is_no_data_result(method: str, result) -> bool:
    if not isinstance(result, str):
        return False

    normalized_result = result.strip()
    if not normalized_result:
        return False

    for prefix in _NO_DATA_PREFIXES.get(method, ()):
        if normalized_result.startswith(prefix):
            return True

    for substring in _NO_DATA_SUBSTRINGS.get(method, ()):
        if substring in normalized_result:
            return True

    return False


def _is_recoverable_vendor_exception(vendor: str, exc: Exception) -> bool:
    if isinstance(exc, (AlphaVantageRateLimitError, TigerOpenRecoverableError)):
        return True

    return (
        vendor == "alpha_vantage"
        and isinstance(exc, ValueError)
        and "ALPHA_VANTAGE_API_KEY environment variable is not set." in str(exc)
    )
