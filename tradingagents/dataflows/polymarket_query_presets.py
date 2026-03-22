from __future__ import annotations

from typing import Iterable


_SUFFIXES_TO_STRIP = (
    ".HK",
)


def normalize_company_aliases(ticker: str, company_name: str) -> list[str]:
    aliases = [
        str(ticker or "").strip(),
        str(company_name or "").strip(),
    ]

    normalized = []
    for alias in aliases:
        if not alias:
            continue
        normalized.append(alias)
        normalized.append(alias.upper())
        normalized.extend(_expand_symbol_aliases(alias))

    return _dedupe_preserve_order(normalized)


def build_company_queries(
    ticker: str,
    company_name: str,
    overrides: Iterable[str] | None = None,
) -> list[str]:
    aliases = normalize_company_aliases(ticker, company_name)
    queries = list(aliases)

    for alias in aliases:
        queries.append(f"{alias} earnings")
        queries.append(f"{alias} guidance")
        queries.append(f"{alias} regulation")
        queries.append(f"{alias} tariffs")
        queries.append(f"{alias} sanctions")
        queries.append(f"{alias} supply chain")
        queries.append(f"{alias} export controls")

    if overrides:
        queries.extend(str(item).strip() for item in overrides if str(item).strip())

    return _dedupe_preserve_order(queries)


def build_macro_queries(
    company_name: str,
    overrides: Iterable[str] | None = None,
) -> list[str]:
    company_aliases = normalize_company_aliases(company_name, company_name)
    base_terms = [
        "Federal Reserve",
        "recession",
        "interest rates",
        "regulation",
        "tariffs",
        "sanctions",
        "supply chain",
        "export controls",
    ]

    queries = list(base_terms)
    for alias in company_aliases:
        for term in base_terms:
            queries.append(f"{alias} {term}")

    if overrides:
        queries.extend(str(item).strip() for item in overrides if str(item).strip())

    return _dedupe_preserve_order(queries)


def build_geopolitical_queries(
    ticker: str,
    company_name: str,
    geo_watchlist: Iterable[str],
    overrides: Iterable[str] | None = None,
) -> list[str]:
    aliases = normalize_company_aliases(ticker, company_name)
    queries = [str(item).strip() for item in geo_watchlist if str(item).strip()]

    for alias in aliases:
        for watch in geo_watchlist:
            watch_term = str(watch).strip()
            if not watch_term:
                continue
            queries.append(f"{alias} {watch_term}")

    if overrides:
        queries.extend(str(item).strip() for item in overrides if str(item).strip())

    return _dedupe_preserve_order(queries)


def slugify_tag(term: str) -> str:
    lowered = str(term or "").strip().lower()
    if not lowered:
        return ""

    parts = []
    last_was_dash = False
    for char in lowered:
        if char.isalnum():
            parts.append(char)
            last_was_dash = False
            continue
        if last_was_dash:
            continue
        parts.append("-")
        last_was_dash = True

    slug = "".join(parts).strip("-")
    return slug


def _expand_symbol_aliases(alias: str) -> list[str]:
    stripped = alias.strip().upper()
    if not stripped:
        return []

    expanded = []
    for suffix in _SUFFIXES_TO_STRIP:
        if stripped.endswith(suffix):
            expanded.append(stripped[: -len(suffix)])

    if stripped.startswith("HK."):
        expanded.append(stripped[3:])

    digits_only = stripped.lstrip("0")
    if digits_only.isdigit():
        expanded.append(digits_only)

    return [item for item in expanded if item]


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        item = str(value).strip()
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
