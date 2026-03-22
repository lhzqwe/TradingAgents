from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_polymarket_company_context(
    ticker: Annotated[str, "Ticker symbol or company identifier"],
    company_name: Annotated[str, "Company name or ticker text used for query expansion"],
    trade_date: Annotated[str, "Trade date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve Polymarket company-specific prediction market context.
    Uses the configured prediction_market_data vendor.
    """
    return route_to_vendor(
        "get_polymarket_company_context",
        ticker,
        company_name,
        trade_date,
    )


@tool
def get_polymarket_macro_context(
    company_name: Annotated[str, "Company name or ticker text used for query expansion"],
    trade_date: Annotated[str, "Trade date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve Polymarket macro prediction market context.
    Uses the configured prediction_market_data vendor.
    """
    return route_to_vendor(
        "get_polymarket_macro_context",
        company_name,
        trade_date,
    )


@tool
def get_polymarket_geopolitical_context(
    ticker: Annotated[str, "Ticker symbol or company identifier"],
    company_name: Annotated[str, "Company name or ticker text used for query expansion"],
    trade_date: Annotated[str, "Trade date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve Polymarket geopolitical prediction market context.
    Uses the configured prediction_market_data vendor.
    """
    return route_to_vendor(
        "get_polymarket_geopolitical_context",
        ticker,
        company_name,
        trade_date,
    )
