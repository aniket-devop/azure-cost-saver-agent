"""Shared detector plumbing: context, result container, row helpers, cost attribution."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from ..collectors.costs import ResourceCosts
from ..models import CostBasis, Evidence, Finding, MonthlyCost

UNAVAILABLE = MonthlyCost(amount=None, currency=None, basis=CostBasis.UNAVAILABLE)


@dataclass(frozen=True)
class DetectionContext:
    subscription_id: str
    now: datetime
    costs: ResourceCosts | None = None


@dataclass
class DetectionResult:
    findings: list[Finding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # something failed; data may be missing
    notes: list[str] = field(default_factory=list)  # limitations the report must show

    def extend(self, other: DetectionResult) -> None:
        self.findings.extend(other.findings)
        self.errors.extend(other.errors)
        for n in other.notes:
            if n not in self.notes:
                self.notes.append(n)


def text(row: Mapping[str, Any], key: str) -> str:
    v = row.get(key)
    return "" if v is None else str(v).strip()


def required(row: Mapping[str, Any], key: str) -> str:
    v = text(row, key)
    if not v:
        raise KeyError(key)
    return v


_FRACTION = re.compile(r"(\.\d{6})\d+")


def parse_time(value: str) -> datetime | None:
    """Parse ARG timestamps (up to 7 fractional digits, 'Z' suffix). None if unparseable."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(_FRACTION.sub(r"\1", value))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def attribute_cost(
    ctx: DetectionContext, resource_id: str, *, counts_as_savings: bool
) -> tuple[list[Evidence], MonthlyCost]:
    """Trailing 30-day actual cost of the resource, as evidence and (optionally) as savings.

    Savings are only claimed where removing the resource removes its cost (unattached disk/IP).
    Absent from the cost data means unknown (billing lag), never zero.
    """
    costs = ctx.costs
    if costs is None:
        return [], UNAVAILABLE
    amount = costs.amounts.get(resource_id.lower())
    if amount is None:
        return [], UNAVAILABLE
    evidence = [
        Evidence(
            source="cost-management",
            metric=f"actual_cost_{costs.start_date}_to_{costs.end_date}",
            value=float(amount),
            unit=costs.currency,
        )
    ]
    if not counts_as_savings:
        return evidence, UNAVAILABLE
    monthly = (amount * 30 / costs.days).quantize(Decimal("0.01"))
    return evidence, MonthlyCost(
        amount=monthly, currency=costs.currency, basis=CostBasis.ACTUAL_COST
    )
