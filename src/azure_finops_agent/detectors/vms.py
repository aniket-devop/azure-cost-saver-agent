"""Under-utilised VMs. CPU is a hint, not proof, so findings are always POTENTIAL."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from typing import Any

from pydantic import ValidationError

from ..collectors.errors import AzureDataError
from ..collectors.monitor import CpuStats
from ..models import Confidence, Evidence, Finding, FindingStatus
from .base import (
    UNAVAILABLE,
    DetectionContext,
    DetectionResult,
    attribute_cost,
    parse_time,
    required,
    text,
)

CATEGORY = "underutilized_vm"
CpuProvider = Callable[[str], CpuStats]


def detect_underutilized_vms(
    rows: Sequence[Mapping[str, Any]],
    ctx: DetectionContext,
    cpu_provider: CpuProvider,
    *,
    cpu_avg_threshold: float = 5.0,
    cpu_max_threshold: float = 30.0,
    lookback_days: int = 7,
    min_coverage: float = 0.8,
    max_vms: int = 500,
) -> DetectionResult:
    out = DetectionResult()
    not_running = young = sparse = 0
    if len(rows) > max_vms:
        out.notes.append(f"Only the first {max_vms} of {len(rows)} VMs were analysed (bound).")
        rows = rows[:max_vms]

    for row in rows:
        try:
            rid, name = required(row, "id"), required(row, "name")
            power = text(row, "powerState").lower()
            if power and "running" not in power:
                not_running += 1
                continue
            created = parse_time(text(row, "timeCreated"))
            if created is not None and ctx.now - created < timedelta(days=lookback_days):
                young += 1
                continue
            stats = cpu_provider(rid)
        except AzureDataError as exc:
            out.errors.append(f"{CATEGORY}: metrics unavailable for {text(row, 'id')} ({exc})")
            continue
        except (KeyError, ValueError, ValidationError):
            out.errors.append(f"{CATEGORY}: skipped malformed row ({text(row, 'id') or '?'})")
            continue

        if stats.average is None or stats.maximum is None or stats.coverage < min_coverage:
            sparse += 1
            continue
        if stats.average >= cpu_avg_threshold or stats.maximum >= cpu_max_threshold:
            continue

        try:
            evidence = [
                Evidence(
                    source="azure-monitor",
                    metric="cpu_average_pct",
                    value=round(stats.average, 2),
                    unit="%",
                    window_start=stats.window_start,
                    window_end=stats.window_end,
                ),
                Evidence(
                    source="azure-monitor",
                    metric="cpu_max_pct",
                    value=round(stats.maximum, 2),
                    unit="%",
                    window_start=stats.window_start,
                    window_end=stats.window_end,
                ),
                Evidence(
                    source="azure-monitor",
                    metric="hourly_datapoints",
                    value=float(stats.datapoints),
                    unit=f"of {stats.expected_points} expected",
                ),
                Evidence(source="resource-graph", metric="vmSize", value=text(row, "vmSize")),
                Evidence(
                    source="resource-graph", metric="powerState", value=text(row, "powerState")
                ),
            ]
            cost_ev, _ = attribute_cost(ctx, rid, counts_as_savings=False)
            out.findings.append(
                Finding(
                    resource_id=rid,
                    name=name,
                    resource_type="microsoft.compute/virtualmachines",
                    resource_group=required(row, "resourceGroup"),
                    subscription_id=text(row, "subscriptionId") or ctx.subscription_id,
                    region=required(row, "location"),
                    category=CATEGORY,
                    status=FindingStatus.POTENTIAL,
                    reason=(
                        f"CPU averaged {stats.average:.1f}% (threshold {cpu_avg_threshold}%) and "
                        f"peaked at {stats.maximum:.1f}% (threshold {cpu_max_threshold}%) over "
                        f"{lookback_days} days."
                    ),
                    evidence=evidence + cost_ev,
                    confidence=Confidence.MEDIUM if stats.coverage >= 0.95 else Confidence.LOW,
                    # Resizing/stopping saves part of the cost, not all of it: no figure claimed.
                    monthly_cost=UNAVAILABLE,
                    recommended_action=(
                        "Review the workload with its owner. If confirmed under-used, consider "
                        "resizing or deallocating. Memory, network and disk I/O were not "
                        "evaluated. This tool never modifies resources."
                    ),
                    evidence_timestamp=ctx.now,
                )
            )
        except (ValueError, ValidationError):
            out.errors.append(f"{CATEGORY}: could not build finding for {text(row, 'id')}")

    out.notes.append(
        "VM detection uses CPU only (Percentage CPU, hourly). Memory, network and disk I/O are "
        "not evaluated, so findings are potential, not confirmed."
    )
    if not_running:
        out.notes.append(f"{not_running} VM(s) not in running state were skipped.")
    if young:
        out.notes.append(f"{young} VM(s) younger than {lookback_days} days were skipped.")
    if sparse:
        out.notes.append(
            f"{sparse} VM(s) skipped: fewer than {int(min_coverage * 100)}% of expected metric "
            "datapoints were available."
        )
    return out
