"""Rules a report must satisfy before it is rendered or accepted from disk."""

from __future__ import annotations

from ..models import FindingStatus, Report

# CPU-only evidence can suggest, never prove, that a VM is idle. Keep in sync with
# detectors.vms.CATEGORY (a unit test enforces this).
POTENTIAL_ONLY_CATEGORIES = frozenset({"underutilized_vm"})


class ReportInvariantError(ValueError):
    """The report breaks a rule that protects the reader from misleading claims."""


def check_invariants(report: Report) -> None:
    for f in report.findings:
        if f.category in POTENTIAL_ONLY_CATEGORIES and f.status is not FindingStatus.POTENTIAL:
            raise ReportInvariantError(
                f"{f.category} finding for {f.resource_id} must be POTENTIAL, got {f.status.value}"
            )
