import os

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", "./results"),
    "data_cache_dir": os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
        "dataflows/data_cache",
    ),
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.2",
    "quick_think_llm": "gpt-5-mini",
    "backend_url": "https://api.openai.com/v1",
    "auth_profile_id": None,
    "report_language": "english",
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance, tigeropen
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance, tigeropen
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "social_data": "twitter_cli",        # Options: twitter_cli
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
        "prediction_market_data": "polymarket_cli",  # Options: polymarket_cli
    },
    "market_routing": {
        "hk_stock_vendor": "tigeropen",
        "hk_indicator_vendor": "tigeropen",
        "auto_detect_hk": True,
    },
    "tigeropen": {
        "props_path": os.getenv("TIGER_CONFIG_PATH"),
        "private_key_path": os.getenv("TIGER_PRIVATE_KEY_PATH"),
        "private_key_pk1": os.getenv("TIGER_PRIVATE_KEY_PK1"),
        "tiger_id": os.getenv("TIGER_ID"),
        "account": os.getenv("TIGER_ACCOUNT"),
        "license": os.getenv("TIGER_LICENSE"),
        "secret_key": os.getenv("TIGER_SECRET_KEY"),
        "lang": "en_US",
        "right": "BR",
        "with_fundamental": True,
        "indicator_history_years": 15,
        "symbol_overrides": {},
    },
    "twitter_cli": {
        "submodule_path": "external/twitter-cli",
        "max_posts": 20,
        "search_product": "Latest",
        "timeout_seconds": 30,
        "query_overrides": {},
    },
    "polymarket_cli_path": os.getenv("POLYMARKET_CLI_PATH"),
    "polymarket_enabled": True,
    "polymarket_mode": "read_only",
    "polymarket_max_markets": 6,
    "polymarket_comments_limit": 20,
    "polymarket_price_history_interval": "1d",
    "polymarket_price_history_fidelity": 30,
    "polymarket_historical_mode": "guarded",
    "polymarket_live_window_days": 2,
    "polymarket_geo_watchlist": [
        "China Taiwan",
        "US China tariffs",
        "Russia Ukraine",
        "Iran Israel",
        "Middle East oil",
        "sanctions",
        "export controls",
        "Federal Reserve",
        "recession",
    ],
    "polymarket_query_overrides": {},
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
}
