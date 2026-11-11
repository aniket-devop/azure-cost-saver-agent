"""Deterministic roll-up of a report: counts and per-currency savings estimates."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from ..models import Finding, FindingStatus, Report
from .common import format_decimal


class ReportStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"  # at least one collection or detection error was recorded


@dataclass(frozen=True)
class CurrencyTotal:
    currency: str
    amount: Decimal
    findings: int


@dataclass(frozen=True)
class ReportSummary:
    status: ReportStatus
    total_findings: int
    confirmed_findings: int
    potential_findings: int
    unknown_cost_findings: int  # confirmed findings whose cost could not be determined
    potential_without_estimate: int  # potential findings: no savings figure by design
    findings_by_category: dict[str, dict[str, int]]
    confirmed_savings: tuple[CurrencyTotal, ...]
    potential_savings: tuple[CurrencyTotal, ...]

    def to_dict(self) -> dict[str, Any]:
        def totals(items: tuple[CurrencyTotal, ...]) -> list[dict[str, Any]]:
            return [
                {"amount": format_decimal(t.amount), "currency": t.currency, "findings": t.findings}
                for t in items
            ]

        return {
            "confirmed_findings": self.confirmed_findings,
            "confirmed_monthly_savings_estimate": totals(self.confirmed_savings),
            "findings_by_category": self.findings_by_category,
            "potential_findings": self.potential_findings,
            "potential_without_estimate": self.potential_without_estimate,
            "potential_monthly_savings_estimate": totals(self.potential_savings),
            "status": self.status.value,
            "total_findings": self.total_findings,
            "unknown_cost_findings": self.unknown_cost_findings,
        }


def has_cost_figure(f: Finding) -> bool:
    c = f.monthly_cost
    return c.amount is not None and c.currency is not None


def _totals(findings: list[Finding]) -> tuple[CurrencyTotal, ...]:
    sums: dict[str, tuple[Decimal, int]] = {}
    for f in findings:
        c = f.monthly_cost
        if c.amount is None or c.currency is None:
            continue  # unknown is skipped, never treated as zero
        total, n = sums.get(c.currency, (Decimal(0), 0))
        sums[c.currency] = (total + c.amount, n + 1)
    return tuple(CurrencyTotal(cur, sums[cur][0], sums[cur][1]) for cur in sorted(sums))


def summarize(report: Report) -> ReportSummary:
    confirmed = [f for f in report.findings if f.status is FindingStatus.CONFIRMED]
    potential = [f for f in report.findings if f.status is FindingStatus.POTENTIAL]
    by_category: dict[str, dict[str, int]] = {}
    for f in report.findings:
        row = by_category.setdefault(f.category, {"confirmed": 0, "potential": 0})
        row[f.status.value] += 1
    return ReportSummary(
        status=ReportStatus.PARTIAL if report.errors else ReportStatus.COMPLETE,
        total_findings=len(report.findings),
        confirmed_findings=len(confirmed),
        potential_findings=len(potential),
        unknown_cost_findings=sum(1 for f in confirmed if not has_cost_figure(f)),
        potential_without_estimate=sum(1 for f in potential if not has_cost_figure(f)),
        findings_by_category={k: by_category[k] for k in sorted(by_category)},
        confirmed_savings=_totals(confirmed),
        potential_savings=_totals(potential),
    )
