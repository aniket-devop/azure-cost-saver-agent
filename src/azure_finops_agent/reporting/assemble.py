"""Combine detector output into one validated, canonically ordered Report."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from ..collectors.costs import ResourceCosts
from ..detectors.base import DetectionResult
from ..models import CostSummary, Finding, Report
from .common import sorted_findings, sorted_unique
from .invariants import check_invariants

NO_RESOURCE_COSTS = (
    "Per-resource cost data was not available; resource costs and savings are shown as Unknown."
)
PARTIAL_RESOURCE_COSTS = (
    "Per-resource cost data may be incomplete (Azure returned more pages than were read); "
    "resources without a cost are shown as Unknown, not zero."
)
NO_TOTAL_COST = (
    "Subscription total cost was not available (cost data can lag 24-48 hours); "
    "it is shown as Unavailable, not zero."
)


def assemble_report(
    *,
    subscription_id: str,
    generated_at: datetime,
    cost_summary: CostSummary | None,
    results: Iterable[DetectionResult],
    costs: ResourceCosts | None = None,
    extra_errors: Iterable[str] = (),
    extra_limitations: Iterable[str] = (),
) -> Report:
    """Merge results. The caller supplies ``generated_at`` so output never depends on the clock.

    Duplicate findings (same category and resource) are dropped and reported as an error so a
    resource can never be counted twice in the savings totals.
    """
    findings: list[Finding] = []
    errors: list[str] = list(extra_errors)
    limitations: list[str] = list(extra_limitations)
    for result in results:
        findings.extend(result.findings)
        errors.extend(result.errors)
        limitations.extend(result.notes)

    if costs is None:
        limitations.append(NO_RESOURCE_COSTS)
    elif costs.partial:
        limitations.append(PARTIAL_RESOURCE_COSTS)
    if cost_summary is None:
        limitations.append(NO_TOTAL_COST)

    unique: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for f in sorted_findings(findings):
        key = (f.category, f.resource_id.lower())
        if key in seen:
            errors.append(f"duplicate finding dropped: {f.category} {f.resource_id}")
            continue
        seen.add(key)
        unique.append(f)

    report = Report(
        generated_at=generated_at,
        subscription_id=subscription_id,
        cost_summary=cost_summary,
        findings=unique,
        errors=sorted_unique(errors),
        limitations=sorted_unique(limitations),
    )
    check_invariants(report)
    return report
