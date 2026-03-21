from __future__ import annotations

from dataclasses import dataclass
import re


MARKET_AUTO = "AUTO"
MARKET_US = "US"
MARKET_HK = "HK"
VALID_MARKETS = {MARKET_AUTO, MARKET_US, MARKET_HK}

_HK_DOT_SUFFIX = re.compile(r"^(?P<digits>\d{1,5})\.HK$")
_HK_DOT_PREFIX = re.compile(r"^HK\.(?P<digits>\d{1,5})$")
_HK_DIGITS = re.compile(r"^(?P<digits>\d{1,5})$")


@dataclass(frozen=True)
class ResolvedMarketSymbol:
    raw_symbol: str
    normalized_symbol: str
    market: str
    tiger_symbol: str
    yfinance_symbol: str

    @property
    def is_hk(self) -> bool:
        return self.market == MARKET_HK


def normalize_market_input(market: str | None, default: str = MARKET_AUTO) -> str:
    if market is None:
        return default

    normalized = str(market).strip().upper()
    if not normalized:
        return default

    if normalized not in VALID_MARKETS:
        raise ValueError(
            f"Unsupported market '{market}'. Choose from: {', '.join(sorted(VALID_MARKETS))}."
        )

    return normalized


def resolve_market_and_symbols(
    symbol: str,
    market: str | None = None,
) -> ResolvedMarketSymbol:
    normalized_symbol = str(symbol).strip().upper()
    requested_market = normalize_market_input(market)

    hk_digits = _extract_hk_digits(normalized_symbol)
    if requested_market == MARKET_HK or (
        requested_market == MARKET_AUTO and hk_digits is not None
    ):
        if hk_digits is not None:
            tiger_symbol = hk_digits.zfill(max(5, len(hk_digits)))
            yfinance_digits = hk_digits
            if len(yfinance_digits) == 5 and yfinance_digits.startswith("0"):
                yfinance_digits = yfinance_digits[1:]
            yfinance_symbol = f"{yfinance_digits.zfill(max(4, len(yfinance_digits)))}.HK"
        else:
            tiger_symbol = normalized_symbol
            yfinance_symbol = normalized_symbol

        return ResolvedMarketSymbol(
            raw_symbol=str(symbol),
            normalized_symbol=normalized_symbol,
            market=MARKET_HK,
            tiger_symbol=tiger_symbol,
            yfinance_symbol=yfinance_symbol,
        )

    market_value = requested_market if requested_market != MARKET_AUTO else MARKET_US
    return ResolvedMarketSymbol(
        raw_symbol=str(symbol),
        normalized_symbol=normalized_symbol,
        market=market_value,
        tiger_symbol=normalized_symbol,
        yfinance_symbol=normalized_symbol,
    )


def _extract_hk_digits(symbol: str) -> str | None:
    for pattern in (_HK_DOT_SUFFIX, _HK_DOT_PREFIX, _HK_DIGITS):
        match = pattern.fullmatch(symbol)
        if match:
            return match.group("digits")
    return None
