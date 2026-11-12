"""Collector nodes: the only stages that call Azure. Each wraps a Phase 2 collector.

Collectors run in parallel. Cost Management throttles aggressively per scope, so its two queries
share a one-slot gate; Resource Graph queries and Azure Monitor calls run concurrently (Monitor
calls through a bounded worker pool).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from ..collectors.costs import get_resource_costs, get_total_cost
from ..collectors.errors import AzureDataError
from ..collectors.graph import query_all
from ..collectors.monitor import CpuStats, get_cpu_stats
from ..detectors import queries
from ..detectors.base import text
from .deps import WorkflowDeps
from .nodes import NodeFn, NodeResult
from .state import WorkflowState
from .timeouts import StageTimeout, call_with_timeout

METRICS_OP = "azure-monitor metrics"
RESOURCE_COST_DAYS = 30  # the detectors scale this window to a 30-day month


def _graph_collector(deps: WorkflowDeps, query: str, rows_key: str, what: str) -> NodeFn:
    def run(state: WorkflowState) -> NodeResult:
        def call() -> Any:
            return query_all(
                deps.clients.graph,
                deps.settings.subscription_id,
                query,
                sleep=deps.clock.sleep,
            )

        result = call_with_timeout(call, deps.limits.collector_timeout_s, label=rows_key)
        update: dict[str, Any] = {rows_key: result.rows}
        if result.truncated:
            update["limitations"] = [
                f"Resource Graph results for {what} were truncated; the list may be incomplete."
            ]
        return NodeResult(update, f"{len(result.rows)} rows")

    return run


def collect_disks(deps: WorkflowDeps) -> NodeFn:
    return _graph_collector(deps, queries.DISKS, "disk_rows", "unattached disks")


def collect_public_ips(deps: WorkflowDeps) -> NodeFn:
    return _graph_collector(deps, queries.PUBLIC_IPS, "ip_rows", "unattached public IPs")


def collect_total_cost(deps: WorkflowDeps, cost_gate: threading.Semaphore) -> NodeFn:
    def run(state: WorkflowState) -> NodeResult:
        now = state["started_at"]

        def call() -> Any:
            with cost_gate:
                return get_total_cost(
                    deps.clients.cost,
                    deps.settings.subscription_id,
                    days=deps.settings.lookback_days,
                    now=now,
                    sleep=deps.clock.sleep,
                )

        summary = call_with_timeout(call, deps.limits.cost_timeout_s, label="total_cost")
        return NodeResult(
            {"total_cost": summary}, "no cost rows returned" if summary is None else ""
        )

    return run


def collect_resource_costs(deps: WorkflowDeps, cost_gate: threading.Semaphore) -> NodeFn:
    def run(state: WorkflowState) -> NodeResult:
        now = state["started_at"]

        def call() -> Any:
            with cost_gate:
                return get_resource_costs(
                    deps.clients.cost,
                    deps.settings.subscription_id,
                    days=RESOURCE_COST_DAYS,
                    now=now,
                    sleep=deps.clock.sleep,
                )

        costs = call_with_timeout(call, deps.limits.cost_timeout_s, label="resource_costs")
        detail = "no cost rows returned" if costs is None else f"{len(costs.amounts)} resources"
        return NodeResult({"resource_costs": costs}, detail)

    return run


def _wants_metrics(row: Mapping[str, Any]) -> bool:
    """Conservative superset of the VMs the detector will ask about (it also skips young VMs).

    The detector stays the single authority; a VM not collected here is reported by the detector
    as an explicit "not collected" error, never silently treated as idle or busy.
    """
    power = text(row, "powerState").lower()
    return not power or "running" in power


def _collect_one(
    deps: WorkflowDeps, rid: str, now: datetime, deadline: float
) -> CpuStats | AzureDataError:
    if deps.clock.monotonic() > deadline:
        return AzureDataError(METRICS_OP, "skipped: metrics collection time budget exceeded")

    def call() -> CpuStats:
        return get_cpu_stats(
            deps.clients.monitor,
            rid,
            lookback_days=deps.settings.lookback_days,
            now=now,
            sleep=deps.clock.sleep,
        )

    try:
        return call_with_timeout(call, deps.limits.metrics_call_timeout_s, label="cpu")
    except AzureDataError as exc:
        return exc
    except StageTimeout as exc:
        return AzureDataError(METRICS_OP, str(exc))
    except Exception as exc:
        return AzureDataError(METRICS_OP, type(exc).__name__)


def collect_cpu(
    deps: WorkflowDeps, rows: list[dict[str, Any]], now: datetime
) -> dict[str, CpuStats | AzureDataError]:
    """Fetch CPU stats for candidate VMs concurrently, bounded by ``limits.max_workers``."""
    ids: list[str] = []
    seen: set[str] = set()
    for row in rows[: deps.limits.max_vms]:
        rid = text(row, "id")
        if rid and rid not in seen and _wants_metrics(row):
            seen.add(rid)
            ids.append(rid)
    deadline = deps.clock.monotonic() + deps.limits.metrics_budget_s
    results: dict[str, CpuStats | AzureDataError] = {}
    if not ids:
        return results
    with ThreadPoolExecutor(
        max_workers=min(deps.limits.max_workers, len(ids)), thread_name_prefix="metrics"
    ) as pool:
        futures = {rid: pool.submit(_collect_one, deps, rid, now, deadline) for rid in ids}
        for rid, future in futures.items():
            results[rid] = future.result()
    return results


def collect_vms(deps: WorkflowDeps) -> NodeFn:
    def run(state: WorkflowState) -> NodeResult:
        def call() -> Any:
            return query_all(
                deps.clients.graph,
                deps.settings.subscription_id,
                queries.VMS,
                sleep=deps.clock.sleep,
            )

        result = call_with_timeout(call, deps.limits.collector_timeout_s, label="vm_rows")
        cpu = collect_cpu(deps, result.rows, state["started_at"])
        update: dict[str, Any] = {"vm_rows": result.rows, "vm_cpu": cpu}
        if result.truncated:
            update["limitations"] = [
                "Resource Graph results for virtual machines were truncated; "
                "the list may be incomplete."
            ]
        failed = sum(1 for v in cpu.values() if isinstance(v, AzureDataError))
        detail = f"{len(result.rows)} VMs, metrics for {len(cpu) - failed}/{len(cpu)}"
        return NodeResult(update, detail)

    return run
