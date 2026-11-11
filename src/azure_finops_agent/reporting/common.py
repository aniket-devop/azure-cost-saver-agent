"""Deterministic ordering and formatting helpers shared by the report renderers.

Nothing here reads the clock, the locale or the operating system, so the output is identical on
Windows and Linux.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from ..models import Finding, FindingStatus

_STATUS_RANK = {FindingStatus.CONFIRMED: 0, FindingStatus.POTENTIAL: 1}


def finding_sort_key(f: Finding) -> tuple[int, str, str, str, str]:
    """Confirmed first, then category, then resource ID (case-insensitive, then exact)."""
    return (_STATUS_RANK[f.status], f.category, f.resource_id.lower(), f.resource_id, f.name)


def sorted_findings(findings: Iterable[Finding]) -> list[Finding]:
    return sorted(findings, key=finding_sort_key)


def sorted_unique(items: Iterable[str]) -> list[str]:
    """Strip, drop blanks, de-duplicate and sort (code-point order, platform independent)."""
    return sorted({s.strip() for s in items if s and s.strip()})


def format_timestamp(value: datetime) -> str:
    """Canonical UTC timestamp, e.g. 2026-11-11T12:00:00Z (fractional seconds only if present)."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def format_decimal(value: Decimal) -> str:
    """Plain positional notation, never scientific (str(Decimal('1E+1')) would be '1E+1')."""
    return format(value, "f")


def format_money(amount: Decimal, currency: str) -> str:
    """Locale-independent, e.g. 'INR 1,234.50'."""
    return f"{currency} {amount:,.2f}"


def format_number(value: float) -> str:
    """Up to 4 decimals, trailing zeros trimmed. Non-finite values are shown as n/a."""
    if not math.isfinite(value):
        return "n/a"
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text
