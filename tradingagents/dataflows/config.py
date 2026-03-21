import copy
from contextvars import ContextVar
import tradingagents.default_config as default_config
from typing import Dict, Optional

# Use default config but allow it to be overridden
_config: Optional[Dict] = None
_runtime_context: ContextVar[Dict] = ContextVar("_runtime_context", default={})


def initialize_config():
    """Initialize the configuration with default values."""
    global _config
    if _config is None:
        _config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def set_config(config: Dict):
    """Update the configuration with custom values."""
    global _config
    if _config is None:
        _config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    _config.update(config)


def get_config() -> Dict:
    """Get the current configuration."""
    if _config is None:
        initialize_config()
    return copy.deepcopy(_config)


def set_runtime_context(context: Dict):
    """Set per-analysis runtime context without mutating config."""
    _runtime_context.set(dict(context or {}))


def get_runtime_context() -> Dict:
    """Get the current per-analysis runtime context."""
    return dict(_runtime_context.get())


def clear_runtime_context():
    """Clear the per-analysis runtime context."""
    _runtime_context.set({})


# Initialize with default config
initialize_config()
