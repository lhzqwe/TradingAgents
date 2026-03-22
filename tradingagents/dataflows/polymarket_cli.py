from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import get_config
from .polymarket_query_presets import (
    build_company_queries,
    build_geopolitical_queries,
    build_macro_queries,
    normalize_company_aliases,
    slugify_tag,
)


_CACHE_TTL_SECONDS = 300
_CLI_TIMEOUT_SECONDS = 20
_DEFAULT_TOP_MARKETS = 6
_DEFAULT_COMMENTS_LIMIT = 20
_NEGATIVE_EVENT_KEYWORDS = {
    "attack",
    "conflict",
    "controls",
    "crash",
    "cutoff",
    "export control",
    "hike",
    "inflation",
    "invasion",
    "oil spike",
    "recession",
    "regulation",
    "sanction",
    "supply chain",
    "tariff",
    "war",
}
_POSITIVE_EVENT_KEYWORDS = {
    "beat",
    "ceasefire",
    "cut rates",
    "easing",
    "guidance raise",
    "growth",
    "record revenue",
    "stimulus",
}


def get_polymarket_company_context(ticker: str, company_name: str, trade_date: str) -> str:
    config = get_config()
    availability_report = _guard_or_disable_report(
        context_name="Company Context",
        trade_date=trade_date,
        config=config,
    )
    if availability_report:
        return availability_report

    overrides = _get_query_overrides(config, ticker, company_name)
    queries = build_company_queries(ticker, company_name, overrides)
    aliases = normalize_company_aliases(ticker, company_name)
    markets, errors = _collect_markets_for_queries(
        queries,
        aliases,
        limit=_search_pool_limit(config),
    )
    selected = _select_relevant_markets(
        markets,
        aliases,
        max_markets=_get_max_markets(config),
        trade_date=trade_date,
    )
    if not selected:
        return _format_unavailable_report(
            title=f"Polymarket Company Context for {ticker}",
            trade_date=trade_date,
            reason=_select_unavailable_reason(
                errors,
                "No relevant live prediction markets matched the company queries.",
            ),
            guarded=False,
        )

    enriched = _enrich_markets(
        selected,
        comments_limit=_get_comments_limit(config),
        interval=str(config.get("polymarket_price_history_interval", "1d")),
        fidelity=int(config.get("polymarket_price_history_fidelity", 30)),
    )
    if not enriched:
        return _format_unavailable_report(
            title=f"Polymarket Company Context for {ticker}",
            trade_date=trade_date,
            reason="Relevant markets were found, but live market details were unavailable from the CLI.",
            guarded=False,
        )

    return _format_context_report(
        title=f"Polymarket Company Context for {ticker}",
        trade_date=trade_date,
        enriched_markets=enriched,
    )


def get_polymarket_macro_context(company_name: str, trade_date: str) -> str:
    config = get_config()
    availability_report = _guard_or_disable_report(
        context_name="Macro Context",
        trade_date=trade_date,
        config=config,
    )
    if availability_report:
        return availability_report

    overrides = _get_query_overrides(config, company_name)
    queries = build_macro_queries(company_name, overrides)
    aliases = normalize_company_aliases(company_name, company_name)
    markets, errors = _collect_markets_for_queries(
        queries,
        aliases,
        limit=_search_pool_limit(config),
    )
    tagged_markets, tagged_errors = _collect_markets_from_event_tags(
        ["Federal Reserve", "recession", "tariffs", "sanctions", "export controls"],
        aliases,
        limit=max(_get_max_markets(config), 4),
    )
    markets.extend(tagged_markets)
    errors.extend(tagged_errors)
    selected = _select_relevant_markets(
        markets,
        aliases,
        max_markets=_get_max_markets(config),
        trade_date=trade_date,
    )
    if not selected:
        return _format_unavailable_report(
            title=f"Polymarket Macro Context for {company_name}",
            trade_date=trade_date,
            reason=_select_unavailable_reason(
                errors,
                "No live macro prediction markets were relevant to the current company context.",
            ),
            guarded=False,
        )

    enriched = _enrich_markets(
        selected,
        comments_limit=_get_comments_limit(config),
        interval=str(config.get("polymarket_price_history_interval", "1d")),
        fidelity=int(config.get("polymarket_price_history_fidelity", 30)),
    )
    return _format_context_report(
        title=f"Polymarket Macro Context for {company_name}",
        trade_date=trade_date,
        enriched_markets=enriched,
    )


def get_polymarket_geopolitical_context(
    ticker: str,
    company_name: str,
    trade_date: str,
) -> str:
    config = get_config()
    availability_report = _guard_or_disable_report(
        context_name="Geopolitical Context",
        trade_date=trade_date,
        config=config,
    )
    if availability_report:
        return availability_report

    geo_watchlist = list(config.get("polymarket_geo_watchlist", []) or [])
    overrides = _get_query_overrides(config, ticker, company_name)
    queries = build_geopolitical_queries(ticker, company_name, geo_watchlist, overrides)
    aliases = normalize_company_aliases(ticker, company_name)
    markets, errors = _collect_markets_for_queries(
        queries,
        aliases,
        limit=_search_pool_limit(config),
    )
    tagged_markets, tagged_errors = _collect_markets_from_event_tags(
        geo_watchlist,
        aliases,
        limit=max(_get_max_markets(config), 4),
    )
    markets.extend(tagged_markets)
    errors.extend(tagged_errors)
    selected = _select_relevant_markets(
        markets,
        aliases,
        max_markets=_get_max_markets(config),
        trade_date=trade_date,
    )
    if not selected:
        return _format_unavailable_report(
            title=f"Polymarket Geopolitical Context for {ticker}",
            trade_date=trade_date,
            reason=_select_unavailable_reason(
                errors,
                "No live geopolitical prediction markets matched the watchlist queries.",
            ),
            guarded=False,
        )

    enriched = _enrich_markets(
        selected,
        comments_limit=_get_comments_limit(config),
        interval=str(config.get("polymarket_price_history_interval", "1d")),
        fidelity=int(config.get("polymarket_price_history_fidelity", 30)),
    )
    return _format_context_report(
        title=f"Polymarket Geopolitical Context for {ticker}",
        trade_date=trade_date,
        enriched_markets=enriched,
    )


def _run_polymarket_json(args: list[str]) -> dict | list:
    config = get_config()
    command_prefix = _resolve_polymarket_command(config)
    cache_key = [*command_prefix, "-o", "json", *args]
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    command = [*command_prefix, "-o", "json", *args]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_CLI_TIMEOUT_SECONDS,
            cwd=str(Path(config["project_dir"]).parent),
        )
    except FileNotFoundError:
        return _error_payload("Polymarket CLI executable was not found.")
    except subprocess.TimeoutExpired:
        return _error_payload("Polymarket CLI command timed out.")
    except Exception as exc:
        return _error_payload(f"Polymarket CLI command failed: {exc}")

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if not stdout:
        if completed.returncode != 0:
            return _error_payload(
                stderr or f"Polymarket CLI exited with code {completed.returncode}.",
                returncode=completed.returncode,
            )
        return _error_payload("Polymarket CLI returned empty stdout.")

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return _error_payload("Polymarket CLI returned malformed JSON output.")

    if completed.returncode != 0:
        if isinstance(payload, dict) and "error" in payload:
            message = payload.get("error")
            if isinstance(message, dict):
                message = message.get("message") or message.get("error") or message
            return _error_payload(str(message), returncode=completed.returncode)
        return _error_payload(
            stderr or f"Polymarket CLI exited with code {completed.returncode}.",
            returncode=completed.returncode,
        )

    if isinstance(payload, dict) and "error" in payload:
        message = payload.get("error")
        if isinstance(message, dict):
            message = message.get("message") or message.get("error") or message
        return _error_payload(str(message), returncode=completed.returncode)

    _cache_set(cache_key, payload)
    return payload


def _cache_get(key_parts: list[str]) -> dict | list | None:
    cache_path = _cache_path_for_key(key_parts)
    if not cache_path.exists():
        return None

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    cached_at = payload.get("cached_at")
    if not isinstance(cached_at, (int, float)):
        return None
    if time.time() - float(cached_at) > _CACHE_TTL_SECONDS:
        return None
    return payload.get("data")


def _cache_set(key_parts: list[str], payload: dict | list) -> None:
    cache_path = _cache_path_for_key(key_parts)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "cached_at": time.time(),
        "data": payload,
    }
    cache_path.write_text(json.dumps(envelope, ensure_ascii=True, indent=2), encoding="utf-8")


def _search_markets(query: str, limit: int) -> dict | list:
    return _run_polymarket_json(["markets", "search", query, "--limit", str(limit)])


def _list_events_by_tag(tag: str, limit: int) -> dict | list:
    slug = slugify_tag(tag)
    if not slug:
        return _error_payload("Invalid Polymarket event tag.")
    return _run_polymarket_json(["events", "list", "--tag", slug, "--limit", str(limit)])


def _get_market(market_id_or_slug: str) -> dict | list:
    return _run_polymarket_json(["markets", "get", str(market_id_or_slug)])


def _get_event(event_id: str) -> dict | list:
    return _run_polymarket_json(["events", "get", str(event_id)])


def _get_comments(entity_type: str, entity_id: str, limit: int) -> dict | list:
    payload = _run_polymarket_json(
        [
            "comments",
            "list",
            "--entity-type",
            str(entity_type),
            "--entity-id",
            str(entity_id),
        ]
    )
    if isinstance(payload, list):
        return payload[:limit]
    if isinstance(payload, dict):
        comments = payload.get("comments")
        if isinstance(comments, list):
            payload = dict(payload)
            payload["comments"] = comments[:limit]
    return payload


def _get_midpoint(token_id: str) -> dict | list:
    return _run_polymarket_json(["clob", "midpoint", str(token_id)])


def _get_spread(token_id: str) -> dict | list:
    return _run_polymarket_json(["clob", "spread", str(token_id)])


def _get_book(token_id: str) -> dict | list:
    return _run_polymarket_json(["clob", "book", str(token_id)])


def _get_price_history(token_id: str, interval: str, fidelity: int) -> dict | list:
    return _run_polymarket_json(
        [
            "clob",
            "price-history",
            str(token_id),
            "--interval",
            str(interval),
            "--fidelity",
            str(fidelity),
        ]
    )


def _get_open_interest(condition_id: str) -> dict | list:
    return _run_polymarket_json(["data", "open-interest", str(condition_id)])


def _guard_or_disable_report(
    *,
    context_name: str,
    trade_date: str,
    config: dict,
) -> str | None:
    if not bool(config.get("polymarket_enabled", True)):
        return _format_unavailable_report(
            title=f"Polymarket {context_name}",
            trade_date=trade_date,
            reason="Polymarket integration is disabled in the current configuration.",
            guarded=False,
        )

    if str(config.get("polymarket_mode", "read_only")).lower() != "read_only":
        return _format_unavailable_report(
            title=f"Polymarket {context_name}",
            trade_date=trade_date,
            reason="Polymarket integration is not configured in read-only mode.",
            guarded=False,
        )

    if str(config.get("polymarket_historical_mode", "guarded")).lower() != "guarded":
        return None

    try:
        trade_day = datetime.strptime(trade_date, "%Y-%m-%d").date()
    except ValueError:
        return _format_unavailable_report(
            title=f"Polymarket {context_name}",
            trade_date=trade_date,
            reason="The supplied trade_date is not a valid yyyy-mm-dd date.",
            guarded=False,
        )

    live_window_days = int(config.get("polymarket_live_window_days", 2))
    threshold = _today_local() - timedelta(days=live_window_days)
    if trade_day < threshold:
        return _format_unavailable_report(
            title=f"Polymarket {context_name}",
            trade_date=trade_date,
            reason=(
                f"Guarded historical mode is active. This trade date is older than the live window "
                f"({live_window_days} days), so Polymarket context is intentionally withheld to avoid temporal leakage."
            ),
            guarded=True,
        )
    return None


def _collect_markets_for_queries(
    queries: Iterable[str],
    aliases: Iterable[str],
    limit: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    aggregated: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    per_query_limit = min(max(limit, 1), 10)
    for query in queries:
        payload = _search_markets(query, per_query_limit)
        if _is_error_payload(payload):
            errors.append(str(payload.get("error", "Polymarket query failed.")))
            continue
        for market in _iter_markets(payload):
            key = _market_dedupe_key(market)
            if not key:
                continue
            record = aggregated.setdefault(key, dict(market))
            record.setdefault("_matched_queries", [])
            record["_matched_queries"].append(str(query))
            record["_relevance_score"] = max(
                float(record.get("_relevance_score", 0.0)),
                _query_match_score(market, query, aliases),
            )
    return list(aggregated.values()), errors


def _collect_markets_from_event_tags(
    tags: Iterable[str],
    aliases: Iterable[str],
    limit: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    aggregated: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for tag in tags:
        payload = _list_events_by_tag(str(tag), limit)
        if _is_error_payload(payload):
            errors.append(str(payload.get("error", "Polymarket event query failed.")))
            continue
        for event in _iter_events(payload):
            event_id = _extract_first_non_empty(event, "id", "eventId", "event_id")
            full_event = event
            if event_id:
                event_payload = _get_event(str(event_id))
                if not _is_error_payload(event_payload) and isinstance(event_payload, dict):
                    full_event = event_payload
            for market in _extract_markets_from_event(full_event):
                key = _market_dedupe_key(market)
                if not key:
                    continue
                record = aggregated.setdefault(key, dict(market))
                record.setdefault("_matched_queries", [])
                record["_matched_queries"].append(str(tag))
                record["_relevance_score"] = max(
                    float(record.get("_relevance_score", 0.0)),
                    _query_match_score(market, str(tag), aliases) + 1.0,
                )
    return list(aggregated.values()), errors


def _select_unavailable_reason(errors: list[str], fallback_reason: str) -> str:
    if not errors:
        return fallback_reason
    return f"Polymarket CLI data was unavailable: {errors[0]}"


def _select_relevant_markets(
    markets: list[dict[str, Any]],
    aliases: list[str],
    max_markets: int,
    trade_date: str,
) -> list[dict[str, Any]]:
    try:
        target_trade_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
    except ValueError:
        target_trade_date = None

    enriched_scores = []
    for market in markets:
        score = float(market.get("_relevance_score", 0.0))
        question = _market_question(market).casefold()
        for alias in aliases:
            if alias and alias.casefold() in question:
                score += 2.0
        if _coerce_bool(_extract_first_non_empty(market, "active", "isActive")):
            score += 1.0
        if _coerce_bool(_extract_first_non_empty(market, "acceptingOrders", "accepting_orders")):
            score += 1.5
        closed = _coerce_bool(_extract_first_non_empty(market, "closed", "isClosed"))
        score += -2.0 if closed else 2.0
        liquidity = _coerce_float(
            _extract_first_non_empty(
                market,
                "liquidity",
                "liquidityNum",
                "liquidity_num",
            )
        )
        if liquidity is not None and liquidity >= 10000:
            score += 1.0
        volume = _coerce_float(
            _extract_first_non_empty(
                market,
                "volume",
                "volumeNum",
                "volume_num",
            )
        )
        if volume is not None and volume >= 10000:
            score += 0.5
        market_end = _coerce_datetime(
            _extract_first_non_empty(market, "endDate", "endDateIso", "end_date")
        )
        if target_trade_date is not None and market_end is not None:
            delta_days = abs((market_end.date() - target_trade_date).days)
            score += max(0.0, 2.0 - min(delta_days, 10) * 0.2)
        market = dict(market)
        market["_selected_score"] = score
        enriched_scores.append(market)

    enriched_scores.sort(key=lambda item: item.get("_selected_score", 0.0), reverse=True)
    return enriched_scores[:max_markets]


def _enrich_markets(
    markets: list[dict[str, Any]],
    *,
    comments_limit: int,
    interval: str,
    fidelity: int,
) -> list[dict[str, Any]]:
    enriched = []
    for market in markets:
        market_key = _extract_first_non_empty(market, "slug", "id", "marketSlug")
        market_details = _get_market(str(market_key)) if market_key else {}
        merged_market = _merge_dicts(market, market_details if isinstance(market_details, dict) else {})

        event_id = _extract_first_non_empty(
            merged_market,
            "eventId",
            "event_id",
            "event",
        )
        if isinstance(event_id, dict):
            event_id = _extract_first_non_empty(event_id, "id", "eventId", "event_id")
        if not event_id:
            nested_events = merged_market.get("events")
            if isinstance(nested_events, list) and nested_events and isinstance(nested_events[0], dict):
                event_id = _extract_first_non_empty(
                    nested_events[0],
                    "id",
                    "eventId",
                    "event_id",
                )
        event_payload: dict[str, Any] = {}
        if event_id:
            fetched_event = _get_event(str(event_id))
            if isinstance(fetched_event, dict) and not _is_error_payload(fetched_event):
                event_payload = fetched_event
        elif isinstance(merged_market.get("events"), list):
            nested_events = merged_market.get("events") or []
            if nested_events and isinstance(nested_events[0], dict):
                event_payload = nested_events[0]

        tokens = _extract_tokens(merged_market)
        primary_token = _pick_primary_token(tokens)
        token_id = primary_token.get("token_id")
        condition_id = _extract_first_non_empty(
            merged_market,
            "conditionId",
            "condition_id",
            "conditionID",
        )
        midpoint = _extract_metric_value(_get_midpoint(str(token_id))) if token_id else None
        spread = _extract_metric_value(_get_spread(str(token_id))) if token_id else None
        book = _get_book(str(token_id)) if token_id else {}
        book_depth = _estimate_book_depth(book)
        price_history = _get_price_history(str(token_id), interval, fidelity) if token_id else {}
        delta_24h, delta_7d = _compute_price_deltas(price_history)
        open_interest = _extract_metric_value(_get_open_interest(str(condition_id))) if condition_id else None

        comments_payload = {}
        market_id = _extract_first_non_empty(merged_market, "id", "marketId", "market_id")
        if market_id:
            comments_payload = _get_comments("market", str(market_id), comments_limit)
        if _is_error_payload(comments_payload) and event_id and not isinstance(event_id, dict):
            comments_payload = _get_comments("event", str(event_id), comments_limit)
        comments = _extract_comments(comments_payload, comments_limit)
        comments_summary = _summarize_comments(comments)

        quality_label = _quality_label(
            spread=spread,
            open_interest=open_interest,
            book_depth=book_depth,
            delta_24h=delta_24h,
            delta_7d=delta_7d,
        )
        question = _market_question(merged_market, event_payload)
        transmission_path = _describe_transmission_path(question)
        direction = _classify_direction(
            question=question,
            midpoint=midpoint,
            delta_24h=delta_24h,
            delta_7d=delta_7d,
        )
        crowd_divergence = _crowd_divergence_label(comments_summary, direction)

        enriched.append(
            {
                "market_id": market_id or market_key or "N/A",
                "event_id": _extract_first_non_empty(event_payload, "id", "eventId", "event_id") or "N/A",
                "question": question,
                "midpoint": midpoint,
                "spread": spread,
                "open_interest": open_interest,
                "delta_24h": delta_24h,
                "delta_7d": delta_7d,
                "quality_label": quality_label,
                "book_depth": book_depth,
                "comments_summary": comments_summary,
                "crowd_divergence": crowd_divergence,
                "transmission_path": transmission_path,
                "direction": direction,
                "matched_queries": market.get("_matched_queries", []),
                "token_id": token_id or "N/A",
                "condition_id": condition_id or "N/A",
            }
        )

    return enriched


def _format_context_report(
    *,
    title: str,
    trade_date: str,
    enriched_markets: list[dict[str, Any]],
) -> str:
    bullish = [item for item in enriched_markets if item["direction"] == "bullish"]
    bearish = [item for item in enriched_markets if item["direction"] == "bearish"]
    low_quality = [item for item in enriched_markets if item["quality_label"] == "low"]
    geopolitical = [
        item for item in enriched_markets if _is_geopolitical_question(item["question"])
    ]

    strongest = enriched_markets[0]
    summary_lines = [
        f"## {title}",
        "",
        "### Executive summary",
        f"- Trade date: {trade_date}",
        f"- Top event prior: {_safe_text(strongest['question'])} (midpoint {_fmt_probability(strongest['midpoint'])}, quality {strongest['quality_label']})",
        f"- Event signal mix: {len(bullish)} bullish, {len(bearish)} bearish, {len(low_quality)} low-quality markets.",
        "- Use low-quality markets only as weak evidence; trust spread, open interest, and book depth more than headline wording.",
        "",
        "### Market table",
        "| Question | Market/Event ID | Midpoint | 24h | 7d | Spread | OI | Quality |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]

    for item in enriched_markets:
        summary_lines.append(
            "| {question} | {ids} | {mid} | {d24} | {d7} | {spread} | {oi} | {quality} |".format(
                question=_table_escape(item["question"]),
                ids=_table_escape(f"{item['market_id']} / {item['event_id']}"),
                mid=_fmt_probability(item["midpoint"]),
                d24=_fmt_delta(item["delta_24h"]),
                d7=_fmt_delta(item["delta_7d"]),
                spread=_fmt_probability(item["spread"]),
                oi=_fmt_number(item["open_interest"]),
                quality=item["quality_label"],
            )
        )

    summary_lines.extend(
        [
            "",
            "### Bullish catalysts",
            *_format_catalyst_lines(
                bullish,
                default_line="No high-conviction bullish event surface was detected from Polymarket.",
            ),
            "",
            "### Bearish catalysts",
            *_format_catalyst_lines(
                bearish,
                default_line="No high-conviction bearish event surface was detected from Polymarket.",
            ),
            "",
            "### Watch items",
            *_format_watch_lines(low_quality, enriched_markets),
            "",
            "### Geopolitical linkage",
            *_format_geopolitical_lines(geopolitical, enriched_markets),
        ]
    )
    return "\n".join(summary_lines).strip()


def _format_unavailable_report(
    *,
    title: str,
    trade_date: str,
    reason: str,
    guarded: bool,
) -> str:
    status = "guarded" if guarded else "unavailable"
    lines = [
        f"## {title}",
        "",
        "### Executive summary",
        f"- Trade date: {trade_date}",
        f"- Polymarket context is {status}: {reason}",
        "- The analyst flow should continue without prediction-market data.",
        "",
        "### Market table",
        "| Question | Market/Event ID | Midpoint | 24h | 7d | Spread | OI | Quality |",
        "|---|---|---:|---:|---:|---:|---:|---|",
        f"| No live Polymarket context | N/A | N/A | N/A | N/A | N/A | N/A | {status} |",
        "",
        "### Bullish catalysts",
        "- None from Polymarket in the current mode.",
        "",
        "### Bearish catalysts",
        "- None from Polymarket in the current mode.",
        "",
        "### Watch items",
        f"- {reason}",
        "",
        "### Geopolitical linkage",
        "- No additional Polymarket linkage available.",
    ]
    return "\n".join(lines).strip()


def _iter_markets(payload: dict | list) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("markets", "data", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _iter_events(payload: dict | list) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("events", "data", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _extract_markets_from_event(event_payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(event_payload, dict):
        return []
    value = event_payload.get("markets")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _extract_tokens(market: dict[str, Any]) -> list[dict[str, str]]:
    tokens = []

    raw_tokens = market.get("tokens")
    if isinstance(raw_tokens, list):
        for token in raw_tokens:
            if not isinstance(token, dict):
                continue
            token_id = _extract_first_non_empty(token, "id", "tokenId", "token_id", "clobTokenId")
            label = _extract_first_non_empty(token, "label", "outcome", "name", "title")
            if token_id:
                tokens.append({"token_id": str(token_id), "label": str(label or "")})

    if tokens:
        return tokens

    token_ids = market.get("clobTokenIds") or market.get("tokenIds")
    outcomes = market.get("outcomes") or market.get("outcomeLabels")
    if isinstance(token_ids, str):
        try:
            token_ids = json.loads(token_ids)
        except json.JSONDecodeError:
            token_ids = [token_ids]
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except json.JSONDecodeError:
            outcomes = [outcomes]
    if isinstance(token_ids, list):
        for index, token_id in enumerate(token_ids):
            label = ""
            if isinstance(outcomes, list) and index < len(outcomes):
                label = str(outcomes[index])
            if token_id:
                tokens.append({"token_id": str(token_id), "label": label})
    return tokens


def _pick_primary_token(tokens: list[dict[str, str]]) -> dict[str, str]:
    for token in tokens:
        if token.get("label", "").strip().casefold() == "yes":
            return token
    return tokens[0] if tokens else {}


def _extract_comments(payload: dict | list, limit: int) -> list[str]:
    raw_comments = []
    if isinstance(payload, list):
        raw_comments = payload
    elif isinstance(payload, dict):
        for key in ("comments", "data", "items", "results"):
            if isinstance(payload.get(key), list):
                raw_comments = payload[key]
                break

    comments = []
    for item in raw_comments[:limit]:
        if not isinstance(item, dict):
            continue
        body = _extract_first_non_empty(item, "body", "text", "comment", "content")
        if body:
            comments.append(str(body))
    return comments


def _summarize_comments(comments: list[str]) -> str:
    if not comments:
        return "No public Polymarket comments were available."

    positive = 0
    negative = 0
    for comment in comments:
        lowered = comment.casefold()
        positive += sum(keyword in lowered for keyword in ("bull", "beat", "upside", "growth", "buy", "strong"))
        negative += sum(keyword in lowered for keyword in ("bear", "miss", "downside", "weak", "sell", "risk", "tariff", "sanction"))

    if positive > negative:
        bias = "Comments skew bullish."
    elif negative > positive:
        bias = "Comments skew bearish."
    else:
        bias = "Comments are mixed or low-signal."

    preview = "; ".join(comment.strip().replace("\n", " ")[:120] for comment in comments[:2])
    return f"{bias} Sample narrative: {preview}" if preview else bias


def _compute_price_deltas(payload: dict | list) -> tuple[float | None, float | None]:
    points = _extract_price_points(payload)
    if len(points) < 2:
        return None, None

    latest_ts, latest_price = points[-1]
    delta_24h = latest_price - points[-2][1]

    delta_7d = None
    if latest_ts is not None:
        seven_days_back = latest_ts - timedelta(days=7)
        for point_ts, price in reversed(points[:-1]):
            if point_ts is not None and point_ts <= seven_days_back:
                delta_7d = latest_price - price
                break
    if delta_7d is None:
        delta_7d = latest_price - points[0][1]

    return delta_24h, delta_7d


def _extract_price_points(payload: dict | list) -> list[tuple[datetime | None, float]]:
    raw_points = []
    if isinstance(payload, list):
        raw_points = payload
    elif isinstance(payload, dict):
        for key in ("history", "points", "data", "items", "results"):
            if isinstance(payload.get(key), list):
                raw_points = payload[key]
                break

    points = []
    for item in raw_points:
        if not isinstance(item, dict):
            continue
        price = _coerce_float(_extract_first_non_empty(item, "price", "p", "value", "y"))
        if price is None:
            continue
        timestamp = _coerce_datetime(
            _extract_first_non_empty(item, "timestamp", "time", "t", "date", "x")
        )
        points.append((timestamp, price))

    points.sort(key=lambda entry: entry[0] or datetime.min)
    return points


def _estimate_book_depth(payload: dict | list) -> float | None:
    if not isinstance(payload, dict):
        return None
    bids = payload.get("bids")
    asks = payload.get("asks")
    if not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
        return None

    depth = 0.0
    for side in (bids[:3], asks[:3]):
        for level in side:
            if not isinstance(level, dict):
                continue
            size = _coerce_float(_extract_first_non_empty(level, "size", "amount", "quantity"))
            if size is not None:
                depth += size
    return depth


def _quality_label(
    *,
    spread: float | None,
    open_interest: float | None,
    book_depth: float | None,
    delta_24h: float | None,
    delta_7d: float | None,
) -> str:
    score = 0
    if spread is not None and spread <= 0.03:
        score += 1
    if open_interest is not None and open_interest >= 25000:
        score += 1
    if book_depth is not None and book_depth > 0:
        score += 1
    if _is_consistent_move(delta_24h, delta_7d):
        score += 1

    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def _is_consistent_move(delta_24h: float | None, delta_7d: float | None) -> bool:
    if delta_24h is None and delta_7d is None:
        return False
    if delta_24h is None:
        return abs(delta_7d or 0.0) < 0.05
    if delta_7d is None:
        return abs(delta_24h) < 0.05
    return (delta_24h == 0 and delta_7d == 0) or (delta_24h > 0 and delta_7d > 0) or (delta_24h < 0 and delta_7d < 0)


def _classify_direction(
    *,
    question: str,
    midpoint: float | None,
    delta_24h: float | None,
    delta_7d: float | None,
) -> str:
    bias = 0
    if midpoint is not None:
        if midpoint >= 0.55:
            bias += 1
        elif midpoint <= 0.45:
            bias -= 1
    if delta_24h is not None and abs(delta_24h) >= 0.03:
        bias += 1 if delta_24h > 0 else -1
    if delta_7d is not None and abs(delta_7d) >= 0.05:
        bias += 1 if delta_7d > 0 else -1

    if _question_implies_negative_event(question):
        bias *= -1 if bias != 0 else -1
    elif _question_implies_positive_event(question) and bias == 0:
        bias = 1

    if bias > 0:
        return "bullish"
    if bias < 0:
        return "bearish"
    return "neutral"


def _crowd_divergence_label(comments_summary: str, direction: str) -> str:
    lowered = comments_summary.casefold()
    if "bullish" in lowered and direction == "bearish":
        return "Comments skew bullish while event pricing maps bearish."
    if "bearish" in lowered and direction == "bullish":
        return "Comments skew bearish while event pricing maps bullish."
    return "No strong crowd-vs-price divergence was detected."


def _describe_transmission_path(question: str) -> str:
    lowered = question.casefold()
    if any(keyword in lowered for keyword in ("tariff", "sanction", "export control", "regulation")):
        return "Transmission path: regulation or trade restrictions can hit revenue realization, margins, and supply-chain flexibility."
    if any(keyword in lowered for keyword in ("iran", "israel", "middle east", "oil", "russia", "ukraine")):
        return "Transmission path: energy and geopolitical shocks can change logistics costs, macro risk appetite, and valuation multiples."
    if any(keyword in lowered for keyword in ("federal reserve", "interest", "rates", "recession")):
        return "Transmission path: rates and growth expectations affect discount rates, consumer demand, and broad risk appetite."
    if any(keyword in lowered for keyword in ("earnings", "guidance", "revenue", "sales")):
        return "Transmission path: earnings-linked event pricing flows directly into revenue expectations, margin confidence, and near-term multiple expansion or compression."
    return "Transmission path: event pricing mainly propagates through sentiment, macro risk appetite, and scenario-based valuation changes."


def _format_catalyst_lines(items: list[dict[str, Any]], default_line: str) -> list[str]:
    if not items:
        return [f"- {default_line}"]
    return [
        "- {question} | midpoint {mid}, 24h {d24}, 7d {d7}, quality {quality}. {path}".format(
            question=item["question"],
            mid=_fmt_probability(item["midpoint"]),
            d24=_fmt_delta(item["delta_24h"]),
            d7=_fmt_delta(item["delta_7d"]),
            quality=item["quality_label"],
            path=item["transmission_path"],
        )
        for item in items[:3]
    ]


def _format_watch_lines(low_quality: list[dict[str, Any]], enriched_markets: list[dict[str, Any]]) -> list[str]:
    lines = []
    if low_quality:
        lines.extend(
            f"- Low-quality market to downweight: {item['question']} (spread {_fmt_probability(item['spread'])}, OI {_fmt_number(item['open_interest'])})."
            for item in low_quality[:3]
        )
    divergences = [
        item for item in enriched_markets if "No strong crowd-vs-price divergence" not in item["crowd_divergence"]
    ]
    if divergences:
        lines.extend(f"- Crowd divergence: {item['crowd_divergence']}" for item in divergences[:2])
    if not lines:
        lines.append("- No special watch items beyond normal prediction-market noise.")
    return lines


def _format_geopolitical_lines(geopolitical: list[dict[str, Any]], enriched_markets: list[dict[str, Any]]) -> list[str]:
    items = geopolitical or [item for item in enriched_markets if "risk appetite" in item["transmission_path"]]
    if not items:
        return ["- No additional geopolitical linkage was surfaced by live Polymarket markets."]
    return [
        f"- {item['question']} | {item['transmission_path']}"
        for item in items[:3]
    ]


def _query_match_score(market: dict[str, Any], query: str, aliases: Iterable[str]) -> float:
    question = _market_question(market).casefold()
    query_lower = str(query).casefold()
    score = 0.0
    if query_lower and query_lower in question:
        score += 3.0
    for alias in aliases:
        alias_lower = str(alias).casefold()
        if alias_lower and alias_lower in question:
            score += 2.0
    for token in query_lower.split():
        if token and token in question:
            score += 0.25
    return score


def _market_question(market: dict[str, Any], event_payload: dict[str, Any] | None = None) -> str:
    value = _extract_first_non_empty(
        market,
        "question",
        "title",
        "marketQuestion",
        "groupItemTitle",
        "slug",
    )
    if value:
        return str(value)
    if isinstance(event_payload, dict):
        value = _extract_first_non_empty(event_payload, "title", "name", "question")
        if value:
            return str(value)
    return "Unnamed Polymarket market"


def _market_dedupe_key(market: dict[str, Any]) -> str:
    value = _extract_first_non_empty(market, "id", "slug", "marketId", "market_id")
    return str(value) if value else ""


def _extract_metric_value(payload: dict | list) -> float | None:
    if _is_error_payload(payload):
        return None
    if isinstance(payload, list):
        for item in payload:
            numeric = _extract_metric_value(item)
            if numeric is not None:
                return numeric
        return None
    if isinstance(payload, (int, float, str)):
        return _coerce_float(payload)
    if isinstance(payload, dict):
        for key in ("mid", "midpoint", "spread", "value", "openInterest", "open_interest", "oi"):
            value = payload.get(key)
            numeric = _coerce_float(value)
            if numeric is not None:
                return numeric
    return None


def _extract_first_non_empty(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is None or value == "":
            continue
        return value
    return None


def _merge_dicts(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    for key, value in secondary.items():
        if key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = value
    return merged


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("$", "").replace("¢", "")
        if cleaned.endswith("%"):
            cleaned = cleaned[:-1]
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


def _fmt_probability(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2%}"


def _fmt_delta(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.2%}"


def _fmt_number(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.0f}"


def _safe_text(value: str) -> str:
    return str(value).replace("\n", " ").strip()


def _table_escape(value: str) -> str:
    return _safe_text(value).replace("|", "\\|")


def _question_implies_negative_event(question: str) -> bool:
    lowered = question.casefold()
    return any(keyword in lowered for keyword in _NEGATIVE_EVENT_KEYWORDS)


def _question_implies_positive_event(question: str) -> bool:
    lowered = question.casefold()
    return any(keyword in lowered for keyword in _POSITIVE_EVENT_KEYWORDS)


def _is_geopolitical_question(question: str) -> bool:
    lowered = question.casefold()
    return any(
        keyword in lowered
        for keyword in (
            "china",
            "taiwan",
            "tariff",
            "sanction",
            "russia",
            "ukraine",
            "iran",
            "israel",
            "middle east",
            "oil",
            "export control",
        )
    )


def _get_query_overrides(config: dict, *keys: str) -> list[str]:
    overrides = config.get("polymarket_query_overrides", {}) or {}
    values = []
    if not isinstance(overrides, dict):
        return values
    for key in keys:
        if key is None:
            continue
        for candidate in (str(key), str(key).upper()):
            if candidate not in overrides:
                continue
            raw_value = overrides[candidate]
            if isinstance(raw_value, str):
                values.append(raw_value)
            elif isinstance(raw_value, list):
                values.extend(str(item).strip() for item in raw_value if str(item).strip())
    deduped = []
    seen = set()
    for value in values:
        normalized = value.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(value)
    return deduped


def _search_pool_limit(config: dict) -> int:
    return max(int(config.get("polymarket_max_markets", _DEFAULT_TOP_MARKETS)) * 2, _DEFAULT_TOP_MARKETS)


def _get_max_markets(config: dict) -> int:
    return max(int(config.get("polymarket_max_markets", _DEFAULT_TOP_MARKETS)), 1)


def _get_comments_limit(config: dict) -> int:
    return max(int(config.get("polymarket_comments_limit", _DEFAULT_COMMENTS_LIMIT)), 1)


def _cache_path_for_key(key_parts: list[str]) -> Path:
    config = get_config()
    cache_root = Path(config["data_cache_dir"]) / "polymarket"
    key = hashlib.sha256(json.dumps(key_parts, ensure_ascii=True).encode("utf-8")).hexdigest()
    return cache_root / f"{key}.json"


def _error_payload(message: str, *, returncode: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": str(message)}
    if returncode is not None:
        payload["returncode"] = returncode
    return payload


def _is_error_payload(payload: dict | list) -> bool:
    return isinstance(payload, dict) and payload.get("ok") is False and "error" in payload


def _today_local() -> date:
    return date.today()


def _resolve_polymarket_command(config: dict) -> list[str]:
    explicit = str(config.get("polymarket_cli_path") or "").strip()
    if explicit:
        return shlex.split(explicit, posix=os.name != "nt")

    project_root = Path(config["project_dir"]).parent
    submodule_root = project_root / "external" / "polymarket-cli"
    binary_name = "polymarket.exe" if os.name == "nt" else "polymarket"
    release_binary = submodule_root / "target" / "release" / binary_name
    if release_binary.exists():
        return [str(release_binary)]

    cargo_toml = submodule_root / "Cargo.toml"
    if cargo_toml.exists():
        return [
            "cargo",
            "run",
            "--quiet",
            "--manifest-path",
            str(cargo_toml),
            "--",
        ]

    return ["polymarket"]
