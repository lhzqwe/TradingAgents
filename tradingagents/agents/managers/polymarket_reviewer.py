import re

from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.llm_clients.report_language import normalize_report_language
from tradingagents.dataflows.config import get_config


_TOP_EVENT_RE = re.compile(r"- Top event prior:\s*(.+)")
_SIGNAL_MIX_RE = re.compile(
    r"- Event signal mix:\s*(\d+)\s+bullish,\s*(\d+)\s+bearish,\s*(\d+)\s+low-quality markets\.",
    re.IGNORECASE,
)
_QUALITY_RE = re.compile(r"quality\s+([a-z]+)\)", re.IGNORECASE)
_FINAL_PROPOSAL_RE = re.compile(
    r"FINAL TRANSACTION PROPOSAL:\s*\*\*(BUY|HOLD|SELL)\*\*",
    re.IGNORECASE,
)


def create_polymarket_reviewer():
    def polymarket_reviewer_node(state) -> dict:
        ticker = state["company_of_interest"]
        company_name = state["company_of_interest"]
        trade_date = state["trade_date"]
        investment_plan = state.get("investment_plan", "")

        raw_report = route_to_vendor(
            "get_polymarket_company_context",
            ticker,
            company_name,
            trade_date,
        )
        polymarket_report = _format_polymarket_review(
            raw_report=raw_report,
            thesis_direction=_extract_direction(investment_plan),
        )
        return {"polymarket_report": polymarket_report}

    return polymarket_reviewer_node


def _extract_direction(text: str) -> str | None:
    if not text:
        return None
    match = _FINAL_PROPOSAL_RE.search(text)
    if match:
        return match.group(1).upper()
    upper_text = text.upper()
    for value in ("BUY", "HOLD", "SELL"):
        if value in upper_text:
            return value
    return None


def _format_polymarket_review(raw_report: str, thesis_direction: str | None) -> str:
    language = normalize_report_language(get_config().get("report_language"))
    top_event = _extract_top_event(raw_report)
    bullish, bearish, low_quality = _extract_signal_mix(raw_report)
    quality = _extract_quality(top_event or raw_report)

    if _is_guarded_or_unavailable(raw_report):
        return _render_review(
            language=language,
            status=_extract_status(raw_report),
            company_event_pricing=_extract_reason(raw_report),
            market_quality="N/A",
            thesis_check="No live company-level prediction-market context was available.",
            conviction_impact="neutral",
        )

    thesis_check, conviction_impact = _assess_thesis(
        thesis_direction=thesis_direction,
        bullish=bullish,
        bearish=bearish,
    )
    company_event_pricing = (
        f"{top_event} Signal mix: {bullish} bullish / {bearish} bearish / "
        f"{low_quality} low-quality markets."
    )
    market_quality = (
        f"Top surface quality: {quality}. Low-quality markets: {low_quality}."
    )

    return _render_review(
        language=language,
        status="live",
        company_event_pricing=company_event_pricing,
        market_quality=market_quality,
        thesis_check=thesis_check,
        conviction_impact=conviction_impact,
    )


def _extract_top_event(raw_report: str) -> str:
    match = _TOP_EVENT_RE.search(raw_report or "")
    if not match:
        return "No clear top event prior was extracted."
    return match.group(1).strip()


def _extract_signal_mix(raw_report: str) -> tuple[int, int, int]:
    match = _SIGNAL_MIX_RE.search(raw_report or "")
    if not match:
        return 0, 0, 0
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _extract_quality(text: str) -> str:
    match = _QUALITY_RE.search(text or "")
    if not match:
        return "unknown"
    return match.group(1).lower()


def _is_guarded_or_unavailable(raw_report: str) -> bool:
    normalized = (raw_report or "").lower()
    return "polymarket context is guarded" in normalized or "unavailable" in normalized


def _extract_status(raw_report: str) -> str:
    normalized = (raw_report or "").lower()
    if "guarded" in normalized:
        return "guarded"
    if "unavailable" in normalized:
        return "unavailable"
    return "neutral"


def _extract_reason(raw_report: str) -> str:
    lines = [line.strip() for line in (raw_report or "").splitlines() if line.strip()]
    for line in lines:
        if line.startswith("- Polymarket context is"):
            return line.removeprefix("- ").strip()
        if "Polymarket CLI data was unavailable" in line:
            return line
    return "No company-level prediction-market detail was available."


def _assess_thesis(
    thesis_direction: str | None,
    bullish: int,
    bearish: int,
) -> tuple[str, str]:
    if thesis_direction == "BUY" and bearish > bullish:
        return (
            "Company event pricing leans against the current bullish thesis and should be treated as a cautionary cross-check.",
            "caution",
        )
    if thesis_direction == "SELL" and bullish > bearish:
        return (
            "Company event pricing leans against the current bearish thesis and should be treated as a cautionary cross-check.",
            "caution",
        )
    if thesis_direction == "BUY" and bullish > bearish:
        return (
            "Company event pricing modestly supports the current bullish thesis, but only as a secondary signal.",
            "supportive",
        )
    if thesis_direction == "SELL" and bearish > bullish:
        return (
            "Company event pricing modestly supports the current bearish thesis, but only as a secondary signal.",
            "supportive",
        )
    return (
        "Company event pricing does not create a strong directional override versus the current thesis.",
        "neutral",
    )


def _render_review(
    language: str,
    status: str,
    company_event_pricing: str,
    market_quality: str,
    thesis_check: str,
    conviction_impact: str,
) -> str:
    how_to_use_en = (
        "- Use this as a secondary event-pricing check only.\n"
        "- Adjust conviction, watch items, or risk controls; do not let it override the main thesis by itself."
    )
    how_to_use_zh = (
        "- 仅把这部分当作二级事件定价复核。\n"
        "- 只用于调整信心、观察项和风控动作，不应单独推翻主 thesis。"
    )

    if language == "chinese":
        return (
            "## Polymarket Review\n\n"
            f"- Status: `{status}`\n"
            f"- Company Event Pricing: {company_event_pricing}\n"
            f"- Market Quality / Liquidity: {market_quality}\n"
            f"- Thesis Check: {thesis_check}\n"
            f"- Conviction Impact: `{conviction_impact}`\n\n"
            "### How To Use\n"
            f"{how_to_use_zh}"
        )

    return (
        "## Polymarket Review\n\n"
        f"- Status: `{status}`\n"
        f"- Company Event Pricing: {company_event_pricing}\n"
        f"- Market Quality / Liquidity: {market_quality}\n"
        f"- Thesis Check: {thesis_check}\n"
        f"- Conviction Impact: `{conviction_impact}`\n\n"
        "### How To Use\n"
        f"{how_to_use_en}"
    )
