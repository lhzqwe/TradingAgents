from __future__ import annotations

from datetime import datetime
import os

import pandas as pd
from stockstats import wrap

from .config import get_config
from .config import get_runtime_context
from .stockstats_utils import _clean_dataframe
from .tigeropen_common import (
    TigerOpenRecoverableError,
    get_tiger_quote_client,
    get_tigeropen_settings,
    resolve_tiger_symbol,
)


_BEST_IND_PARAMS = {
    "close_50_sma": (
        "50 SMA: A medium-term trend indicator. "
        "Usage: Identify trend direction and serve as dynamic support/resistance. "
        "Tips: It lags price; combine with faster indicators for timely signals."
    ),
    "close_200_sma": (
        "200 SMA: A long-term trend benchmark. "
        "Usage: Confirm overall market trend and identify golden/death cross setups. "
        "Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries."
    ),
    "close_10_ema": (
        "10 EMA: A responsive short-term average. "
        "Usage: Capture quick shifts in momentum and potential entry points. "
        "Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals."
    ),
    "macd": (
        "MACD: Computes momentum via differences of EMAs. "
        "Usage: Look for crossovers and divergence as signals of trend changes. "
        "Tips: Confirm with other indicators in low-volatility or sideways markets."
    ),
    "macds": (
        "MACD Signal: An EMA smoothing of the MACD line. "
        "Usage: Use crossovers with the MACD line to trigger trades. "
        "Tips: Should be part of a broader strategy to avoid false positives."
    ),
    "macdh": (
        "MACD Histogram: Shows the gap between the MACD line and its signal. "
        "Usage: Visualize momentum strength and spot divergence early. "
        "Tips: Can be volatile; complement with additional filters in fast-moving markets."
    ),
    "rsi": (
        "RSI: Measures momentum to flag overbought/oversold conditions. "
        "Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. "
        "Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis."
    ),
    "boll": (
        "Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. "
        "Usage: Acts as a dynamic benchmark for price movement. "
        "Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals."
    ),
    "boll_ub": (
        "Bollinger Upper Band: Typically 2 standard deviations above the middle line. "
        "Usage: Signals potential overbought conditions and breakout zones. "
        "Tips: Confirm signals with other tools; prices may ride the band in strong trends."
    ),
    "boll_lb": (
        "Bollinger Lower Band: Typically 2 standard deviations below the middle line. "
        "Usage: Indicates potential oversold conditions. "
        "Tips: Use additional analysis to avoid false reversal signals."
    ),
    "atr": (
        "ATR: Averages true range to measure volatility. "
        "Usage: Set stop-loss levels and adjust position sizes based on current market volatility. "
        "Tips: It's a reactive measure, so use it as part of a broader risk management strategy."
    ),
    "vwma": (
        "VWMA: A moving average weighted by volume. "
        "Usage: Confirm trends by integrating price action with volume data. "
        "Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses."
    ),
    "mfi": (
        "MFI: The Money Flow Index is a momentum indicator that uses both price and volume to measure buying and selling pressure. "
        "Usage: Identify overbought (>80) or oversold (<20) conditions and confirm the strength of trends or reversals. "
        "Tips: Use alongside RSI or MACD to confirm signals; divergence between price and MFI can indicate potential reversals."
    ),
}


def get_stock_data_tigeropen(symbol: str, start_date: str, end_date: str) -> str:
    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")

    tiger_symbol = resolve_tiger_symbol(symbol.upper())
    settings = get_tigeropen_settings()

    try:
        data = _fetch_tiger_bars(
            tiger_symbol,
            start_date,
            end_date,
            with_fundamental=bool(settings.get("with_fundamental", True)),
        )
    except TigerOpenRecoverableError:
        raise
    except Exception as exc:
        raise TigerOpenRecoverableError(str(exc)) from exc

    if data.empty:
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

    csv_string = data.to_csv()
    header = f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
    header += f"# Total records: {len(data)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    header += "# Data source: tigeropen\n\n"
    return header + csv_string


def get_indicator_tigeropen(
    symbol: str,
    indicator: str,
    curr_date: str,
    look_back_days: int,
) -> str:
    if indicator not in _BEST_IND_PARAMS:
        raise ValueError(
            f"Indicator {indicator} is not supported. Please choose from: {list(_BEST_IND_PARAMS.keys())}"
        )

    curr_date = _resolve_indicator_date(curr_date)
    curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    before = curr_date_dt - pd.DateOffset(days=look_back_days)

    indicator_data = _get_tiger_stock_stats_bulk(symbol, indicator, curr_date)

    current_dt = curr_date_dt
    date_values: list[tuple[str, str]] = []
    while current_dt >= before.to_pydatetime():
        date_str = current_dt.strftime("%Y-%m-%d")
        indicator_value = indicator_data.get(
            date_str,
            "N/A: Not a trading day (weekend or holiday)",
        )
        date_values.append((date_str, indicator_value))
        current_dt = current_dt - pd.DateOffset(days=1)

    ind_string = "".join(f"{date_str}: {value}\n" for date_str, value in date_values)
    return (
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
        f"{ind_string}\n\n{_BEST_IND_PARAMS[indicator]}"
    )


def _get_tiger_stock_stats_bulk(symbol: str, indicator: str, curr_date: str) -> dict:
    config = get_config()
    settings = get_tigeropen_settings()
    history_years = int(settings.get("indicator_history_years", 15))
    today_date = pd.Timestamp.today()
    start_date = (today_date - pd.DateOffset(years=history_years)).strftime("%Y-%m-%d")
    end_date = today_date.strftime("%Y-%m-%d")
    tiger_symbol = resolve_tiger_symbol(symbol.upper())

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{tiger_symbol}-tigeropen-data-{start_date}-{end_date}.csv",
    )

    if os.path.exists(data_file):
        data = pd.read_csv(data_file, on_bad_lines="skip")
    else:
        data = _fetch_tiger_bars(
            tiger_symbol,
            start_date,
            end_date,
            with_fundamental=False,
        ).reset_index()
        data.to_csv(data_file, index=False)

    data = _clean_dataframe(data)
    df = wrap(data)
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    df[indicator]

    result_dict = {}
    for _, row in df.iterrows():
        date_str = row["Date"]
        indicator_value = row[indicator]
        if pd.isna(indicator_value):
            result_dict[date_str] = "N/A"
        else:
            result_dict[date_str] = str(indicator_value)

    return result_dict


def _fetch_tiger_bars(
    symbol: str,
    start_date: str,
    end_date: str,
    with_fundamental: bool,
) -> pd.DataFrame:
    client = get_tiger_quote_client()
    settings = get_tigeropen_settings()
    right = str(settings.get("right", "BR")).lower()

    try:
        bars = client.get_bars_by_page(
            symbol=symbol,
            begin_time=start_date,
            end_time=_next_day(end_date),
            total=10000,
            page_size=1000,
            time_interval=0.01,
            right=right,
            lang=settings.get("lang") or "en_US",
            with_fundamental=with_fundamental,
        )
    except Exception as exc:
        from .tigeropen_common import _map_tiger_exception

        raise _map_tiger_exception(exc) from exc

    if bars is None or bars.empty:
        return pd.DataFrame()

    return _standardize_tiger_bars(bars, start_date, end_date)


def _standardize_tiger_bars(
    bars: pd.DataFrame,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    data = bars.copy()
    data["Date"] = pd.to_datetime(data["time"], unit="ms", utc=True).dt.tz_localize(None)
    data["Date"] = data["Date"].dt.normalize()

    data = data[(data["Date"] >= pd.to_datetime(start_date)) & (data["Date"] <= pd.to_datetime(end_date))]
    if data.empty:
        return pd.DataFrame()

    rename_map = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
        "amount": "Amount",
        "turnover_rate": "Turnover Rate",
        "ttm_pe": "TTM PE",
        "lyr_pe": "LYR PE",
    }
    data = data.rename(columns=rename_map)

    ordered_columns = [
        column
        for column in [
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "Amount",
            "Turnover Rate",
            "TTM PE",
            "LYR PE",
        ]
        if column in data.columns
    ]

    data = data[["Date", *ordered_columns]].drop_duplicates(subset=["Date"]).sort_values("Date")
    data = data.set_index("Date")

    for column in ("Open", "High", "Low", "Close"):
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce").round(2)

    if "Volume" in data.columns:
        data["Volume"] = pd.to_numeric(data["Volume"], errors="coerce")

    return data


def _next_day(date_str: str) -> str:
    return (pd.to_datetime(date_str) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def _resolve_indicator_date(curr_date: str) -> str:
    try:
        datetime.strptime(curr_date, "%Y-%m-%d")
        return curr_date
    except ValueError:
        fallback_date = get_runtime_context().get("trade_date")
        if fallback_date:
            datetime.strptime(fallback_date, "%Y-%m-%d")
            return fallback_date
        raise
