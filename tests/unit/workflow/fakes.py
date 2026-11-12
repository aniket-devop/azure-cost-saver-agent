"""Injected fakes for the Phase 5 tests. Nothing here can reach Azure or the network."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

from azure_finops_agent.config import Settings
from azure_finops_agent.detectors import queries
from azure_finops_agent.workflow import (
    AzureClients,
    ManualClock,
    RunLimits,
    WorkflowDeps,
)

SUB = "11111111-1111-1111-1111-111111111111"
BASE = f"/subscriptions/{SUB}/resourceGroups/rg1/providers"
Hook = Callable[..., Any]


class TransientError(Exception):
    """Looks like an HTTP 503 to the Phase 2 retry logic."""

    status_code = 503


def rid(kind: str, name: str) -> str:
    return f"{BASE}/{kind}/{name}"


def _common(resource_id: str, name: str) -> dict[str, Any]:
    return {
        "id": resource_id,
        "name": name,
        "resourceGroup": "rg1",
        "subscriptionId": SUB,
        "location": "centralindia",
    }


def disk_row(name: str, sku: str = "Premium_LRS", size: int = 128) -> dict[str, Any]:
    return {
        **_common(rid("Microsoft.Compute/disks", name), name),
        "managedBy": "",
        "diskState": "Unattached",
        "skuName": sku,
        "sizeGb": size,
        "timeCreated": "2026-01-05T08:00:00Z",
    }


def ip_row(name: str) -> dict[str, Any]:
    return {
        **_common(rid("Microsoft.Network/publicIPAddresses", name), name),
        "skuName": "Standard",
        "allocation": "Static",
        "ipAddress": "203.0.113.7",
        "ipConfigId": "",
        "natGatewayId": "",
    }


def vm_row(name: str, power: str = "PowerState/running") -> dict[str, Any]:
    return {
        **_common(rid("Microsoft.Compute/virtualMachines", name), name),
        "vmSize": "Standard_D2s_v5",
        "powerState": power,
        "timeCreated": "2026-01-05T08:00:00Z",
    }


class Recorder:
    """Thread-safe call log with an in-flight counter (to prove bounded concurrency)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0

    def enter(self, label: str) -> None:
        with self._lock:
            self.calls.append(label)
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)

    def leave(self) -> None:
        with self._lock:
            self.in_flight -= 1


class FakeGraph:
    def __init__(
        self,
        *,
        disks: list[dict[str, Any]] | None = None,
        ips: list[dict[str, Any]] | None = None,
        vms: list[dict[str, Any]] | None = None,
        hooks: dict[str, Hook] | None = None,
        truncated: set[str] | None = None,
    ) -> None:
        self.rows = {"disks": disks or [], "ips": ips or [], "vms": vms or []}
        self.hooks = hooks or {}
        self.truncated = truncated or set()
        self.recorder = Recorder()

    def resources(self, query: Any, **_: Any) -> Any:
        which = {queries.DISKS: "disks", queries.PUBLIC_IPS: "ips", queries.VMS: "vms"}[query.query]
        self.recorder.enter(which)
        try:
            hook = self.hooks.get(which)
            if hook is not None:
                hook()
            return NS(
                data=list(self.rows[which]),
                skip_token=None,
                result_truncated="true" if which in self.truncated else "false",
            )
        finally:
            self.recorder.leave()


class FakeCost:
    def __init__(
        self,
        *,
        total: float | None = 1000.0,
        per_resource: dict[str, float] | None = None,
        hooks: dict[str, Hook] | None = None,
    ) -> None:
        self.total = total
        self.per_resource = per_resource or {}
        self.hooks = hooks or {}
        self.recorder = Recorder()

    @property
    def query(self) -> FakeCost:
        return self

    def usage(self, scope: str, parameters: Any) -> Any:
        grouped = bool(parameters.dataset.grouping)
        which = "resource" if grouped else "total"
        self.recorder.enter(which)
        try:
            hook = self.hooks.get(which)
            if hook is not None:
                hook()
            if grouped:
                rows = [[v, k.lower(), "INR"] for k, v in sorted(self.per_resource.items())]
                cols = [NS(name="Cost"), NS(name="ResourceId"), NS(name="Currency")]
                return NS(rows=rows, columns=cols, next_link=None)
            if self.total is None:
                return NS(rows=[], columns=[])
            return NS(rows=[[self.total, "INR"]], columns=[NS(name="Cost"), NS(name="Currency")])
        finally:
            self.recorder.leave()


class FakeMonitor:
    def __init__(
        self,
        profiles: dict[str, tuple[float, float]] | None = None,
        *,
        default: tuple[float, float] = (50.0, 90.0),
        hook: Callable[[str], Any] | None = None,
    ) -> None:
        self.profiles = profiles or {}
        self.default = default
        self.hook = hook
        self.recorder = Recorder()

    @property
    def metrics(self) -> FakeMonitor:
        return self

    def list(self, resource_id: str, **_: Any) -> Any:
        self.recorder.enter(resource_id)
        try:
            if self.hook is not None:
                self.hook(resource_id)
            avg, peak = self.profiles.get(resource_id, self.default)
            points = [NS(average=avg, maximum=peak) for _ in range(168)]
            return NS(value=[NS(timeseries=[NS(data=points)])])
        finally:
            self.recorder.leave()


class RecordingNotifier:
    def __init__(self, hook: Callable[[], Any] | None = None) -> None:
        self.hook = hook
        self.messages: list[str] = []

    def send(self, text: str) -> None:
        if self.hook is not None:
            self.hook()
        self.messages.append(text)


class StaticExplainer:
    def __init__(self, reply: str | Exception | Callable[[str], str]) -> None:
        self.reply = reply
        self.received: list[str] = []

    def explain(self, facts: str) -> str:
        self.received.append(facts)
        if isinstance(self.reply, Exception):
            raise self.reply
        if callable(self.reply):
            return self.reply(facts)
        return self.reply


def fast_limits(**overrides: float | int) -> RunLimits:
    """Generous timeouts by default so a slow CI machine cannot cause false failures."""
    base: dict[str, float | int] = {
        "collector_timeout_s": 10.0,
        "cost_timeout_s": 10.0,
        "metrics_call_timeout_s": 10.0,
        "metrics_budget_s": 60.0,
        "explain_timeout_s": 10.0,
        "notify_timeout_s": 10.0,
        "run_budget_s": 1000.0,
    }
    base.update(overrides)
    return RunLimits(**base)  # type: ignore[arg-type]


def make_deps(
    out_dir: Path,
    *,
    graph: FakeGraph | None = None,
    cost: FakeCost | None = None,
    monitor: FakeMonitor | None = None,
    clock: ManualClock | None = None,
    limits: RunLimits | None = None,
    explainer: Any = None,
    notifier: Any = None,
    settings: Settings | None = None,
) -> WorkflowDeps:
    return WorkflowDeps(
        settings=settings or Settings(subscription_id=SUB),
        clients=AzureClients(
            graph=graph or FakeGraph(),
            monitor=monitor or FakeMonitor(),
            cost=cost or FakeCost(),
        ),
        clock=clock or ManualClock(),
        out_dir=out_dir,
        limits=limits or fast_limits(),
        explainer=explainer,
        notifier=notifier,
    )
