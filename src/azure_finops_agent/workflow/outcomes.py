"""What happened to each workflow stage. Partial results are explicit, never implied."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class StageStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class StageOutcome:
    name: str
    status: StageStatus
    detail: str = ""
    duration_s: float = 0.0


# Canonical order used for every listing, so output never depends on thread completion order.
STAGE_ORDER: tuple[str, ...] = (
    "start",
    "collect_total_cost",
    "collect_resource_costs",
    "collect_disks",
    "collect_public_ips",
    "collect_vms",
    "detect_disks",
    "detect_public_ips",
    "detect_vms",
    "assemble",
    "write_reports",
    "explain",
    "notify",
    "finalize",
)


def stage_sort_key(outcome: StageOutcome) -> tuple[int, str]:
    try:
        return (STAGE_ORDER.index(outcome.name), outcome.name)
    except ValueError:
        return (len(STAGE_ORDER), outcome.name)
