from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Create a custom config
config = DEFAULT_CONFIG.copy()
config["deep_think_llm"] = "gpt-5-mini"  # Use a different model
config["quick_think_llm"] = "gpt-5-mini"  # Use a different model
config["max_debate_rounds"] = 1  # Increase debate rounds
# To use ChatGPT OAuth instead of OPENAI_API_KEY:
# config["llm_provider"] = "openai-codex"
# config["auth_profile_id"] = "openai-codex:default"
# config["deep_think_llm"] = "gpt-5.4"
# config["quick_think_llm"] = "gpt-5.4"

# Configure data vendors (default uses yfinance, no extra API keys needed)
config["data_vendors"] = {
    "core_stock_apis": "yfinance",           # Options: alpha_vantage, yfinance, tigeropen
    "technical_indicators": "yfinance",      # Options: alpha_vantage, yfinance, tigeropen
    "fundamental_data": "yfinance",          # Options: alpha_vantage, yfinance
    "social_data": "twitter_cli",            # Options: twitter_cli
    "news_data": "yfinance",                 # Options: alpha_vantage, yfinance
}
config["market_routing"] = {
    "hk_stock_vendor": "tigeropen",
    "hk_indicator_vendor": "tigeropen",
    "auto_detect_hk": True,
}
config["twitter_cli"] = {
    "submodule_path": "external/twitter-cli",
    "max_posts": 20,
    "search_product": "Latest",
    "timeout_seconds": 30,
    "query_overrides": {},
}

# Initialize with custom config
ta = TradingAgentsGraph(debug=True, config=config)

# forward propagate
_, decision = ta.propagate("NVDA", "2024-05-10", market="US")
print(decision)

# Memorize mistakes and reflect
# ta.reflect_and_remember(1000) # parameter is the position returns
