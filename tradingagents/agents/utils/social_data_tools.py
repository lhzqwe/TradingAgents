from langchain_core.tools import tool
from typing import Annotated

from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_social_posts(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve direct social media posts for a given ticker symbol.
    Uses the configured social_data vendor.
    Args:
        ticker (str): Ticker symbol
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing social media posts
    """
    return route_to_vendor("get_social_posts", ticker, start_date, end_date)
