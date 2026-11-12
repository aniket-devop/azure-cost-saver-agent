"""Detector nodes: pure computation over collected data. No Azure access, no I/O, no clock.

A detector whose input was not collected is *skipped* (and the report says so); it never runs on
empty data, because "no rows" would be misread as "nothing wasteful found".
"""

from __future__ import annotations

from collections.abc import Mapping

from ..collectors.errors import AzureDataError
from ..collectors.monitor import CpuStats
from ..detectors import (
    DetectionContext,
    detect_unattached_disks,
    detect_unattached_public_ips,
    detect_underutilized_vms,
)
from ..detectors.vms import CpuProvider
from .deps import WorkflowDeps
from .nodes import NodeFn, NodeResult, StageSkipped
from .state import WorkflowState

NOT_COLLECTED = "{what} data was not collected"
NOT_ANALYSED = "{what} were not analysed because their data could not be collected."


def _context(deps: WorkflowDeps, state: WorkflowState) -> DetectionContext:
    return DetectionContext(
        subscription_id=deps.settings.subscription_id,
        now=state["started_at"],
        costs=state.get("resource_costs"),
    )


def _missing(singular: str, plural: str) -> StageSkipped:
    return StageSkipped(
        NOT_COLLECTED.format(what=singular), limitation=NOT_ANALYSED.format(what=plural)
    )


def detect_disks(deps: WorkflowDeps) -> NodeFn:
    def run(state: WorkflowState) -> NodeResult:
        rows = state.get("disk_rows")
        if rows is None:
            raise _missing("unattached disk", "Unattached disks")
        result = detect_unattached_disks(rows, _context(deps, state))
        return NodeResult({"disk_result": result}, f"{len(result.findings)} findings")

    return run


def detect_public_ips(deps: WorkflowDeps) -> NodeFn:
    def run(state: WorkflowState) -> NodeResult:
        rows = state.get("ip_rows")
        if rows is None:
            raise _missing("unattached public IP", "Unattached public IPs")
        result = detect_unattached_public_ips(rows, _context(deps, state))
        return NodeResult({"ip_result": result}, f"{len(result.findings)} findings")

    return run


def make_cpu_provider(cpu: Mapping[str, CpuStats | AzureDataError]) -> CpuProvider:
    """Serve the CPU stats collected earlier. Anything not collected is an explicit error."""

    def provider(resource_id: str) -> CpuStats:
        found = cpu.get(resource_id)
        if found is None:
            raise AzureDataError("azure-monitor metrics", "not collected")
        if isinstance(found, AzureDataError):
            raise found
        return found

    return provider


def detect_vms(deps: WorkflowDeps) -> NodeFn:
    def run(state: WorkflowState) -> NodeResult:
        rows = state.get("vm_rows")
        if rows is None:
            raise _missing("virtual machine", "Virtual machines")
        settings = deps.settings
        result = detect_underutilized_vms(
            rows,
            _context(deps, state),
            make_cpu_provider(state.get("vm_cpu", {})),
            cpu_avg_threshold=settings.cpu_idle_threshold_pct,
            cpu_max_threshold=settings.cpu_max_threshold_pct,
            lookback_days=settings.lookback_days,
            max_vms=deps.limits.max_vms,
        )
        return NodeResult({"vm_result": result}, f"{len(result.findings)} findings")

    return run
