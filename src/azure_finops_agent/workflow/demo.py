"""Offline demo: the real workflow over synthetic in-memory data. No Azure, no network.

Used by ``azure-finops demo`` so the CLI can be verified (for example in Windows PowerShell)
without credentials. The data is fictional and the subscription ID is the all-zero GUID; reports
produced here must never be mistaken for a real analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace as NS
from typing import Any

from ..config import Settings
from ..detectors import queries
from .clients import AzureClients
from .clock import ManualClock
from .deps import Explainer, Notifier
from .notify import NotificationError

DEMO_SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
SCENARIOS = ("healthy", "partial", "notify-failure", "llm-rejected")
_BASE = f"/subscriptions/{DEMO_SUBSCRIPTION}/resourceGroups/demo-rg/providers"
DISK_1 = f"{_BASE}/Microsoft.Compute/disks/demo-disk-01"
DISK_2 = f"{_BASE}/Microsoft.Compute/disks/demo-disk-02"
IP_1 = f"{_BASE}/Microsoft.Network/publicIPAddresses/demo-ip-01"
VM_IDLE = f"{_BASE}/Microsoft.Compute/virtualMachines/demo-vm-idle"
VM_BUSY = f"{_BASE}/Microsoft.Compute/virtualMachines/demo-vm-busy"
VM_STOPPED = f"{_BASE}/Microsoft.Compute/virtualMachines/demo-vm-stopped"


class DemoServiceError(Exception):
    """A simulated transient Azure failure (HTTP 503)."""

    status_code = 503


def _common(rid: str, name: str) -> dict[str, Any]:
    return {
        "id": rid,
        "name": name,
        "resourceGroup": "demo-rg",
        "subscriptionId": DEMO_SUBSCRIPTION,
        "location": "centralindia",
    }


def _disks() -> list[dict[str, Any]]:
    base = {"managedBy": "", "diskState": "Unattached", "timeCreated": "2026-01-05T08:00:00Z"}
    return [
        {**_common(DISK_1, "demo-disk-01"), **base, "skuName": "Premium_LRS", "sizeGb": 128},
        {**_common(DISK_2, "demo-disk-02"), **base, "skuName": "Standard_LRS", "sizeGb": 64},
    ]


def _ips() -> list[dict[str, Any]]:
    return [
        {
            **_common(IP_1, "demo-ip-01"),
            "skuName": "Standard",
            "allocation": "Static",
            "ipAddress": "203.0.113.10",
            "ipConfigId": "",
            "natGatewayId": "",
        }
    ]


def _vms() -> list[dict[str, Any]]:
    created = "2026-01-05T08:00:00Z"
    return [
        {
            **_common(VM_IDLE, "demo-vm-idle"),
            "vmSize": "Standard_D4s_v5",
            "powerState": "PowerState/running",
            "timeCreated": created,
        },
        {
            **_common(VM_BUSY, "demo-vm-busy"),
            "vmSize": "Standard_D2s_v5",
            "powerState": "PowerState/running",
            "timeCreated": created,
        },
        {
            **_common(VM_STOPPED, "demo-vm-stopped"),
            "vmSize": "Standard_B2s",
            "powerState": "PowerState/deallocated",
            "timeCreated": created,
        },
    ]


# average %, maximum % per running VM (168 hourly points = 7 days)
_CPU = {VM_IDLE: (1.5, 9.0), VM_BUSY: (55.0, 92.0)}


class _DemoGraph:
    def __init__(self, fail_disks: bool) -> None:
        self._fail_disks = fail_disks

    def resources(self, query: Any, **_: Any) -> Any:
        if query.query == queries.DISKS:
            if self._fail_disks:
                raise DemoServiceError("simulated Resource Graph outage")
            rows = _disks()
        elif query.query == queries.PUBLIC_IPS:
            rows = _ips()
        elif query.query == queries.VMS:
            rows = _vms()
        else:  # pragma: no cover - the demo only issues the three known queries
            raise AssertionError("unexpected query")
        return NS(data=rows, skip_token=None, result_truncated="false")


class _DemoCost:
    @property
    def query(self) -> Any:
        return self

    def usage(self, scope: str, parameters: Any) -> Any:
        columns = [NS(name="Cost"), NS(name="ResourceId"), NS(name="Currency")]
        if parameters.dataset.grouping:
            rows = [[600.0, DISK_1.lower(), "INR"], [270.0, IP_1.lower(), "INR"]]
            return NS(rows=rows, columns=columns, next_link=None)
        return NS(rows=[[1234.5, "INR"]], columns=[NS(name="Cost"), NS(name="Currency")])


class _DemoMonitor:
    @property
    def metrics(self) -> Any:
        return self

    def list(self, resource_id: str, **_: Any) -> Any:
        avg, peak = _CPU[resource_id]
        points = [NS(average=avg, maximum=peak) for _ in range(168)]
        return NS(value=[NS(timeseries=[NS(data=points)])])


def build_demo_clients(scenario: str) -> AzureClients:
    return AzureClients(
        graph=_DemoGraph(fail_disks=scenario == "partial"),
        monitor=_DemoMonitor(),
        cost=_DemoCost(),
    )


def demo_settings() -> Settings:
    return Settings(subscription_id=DEMO_SUBSCRIPTION)


def demo_clock() -> ManualClock:
    return ManualClock()


@dataclass
class DemoNotifier:
    """Pretends to be a webhook: records the message, or fails on purpose."""

    fail: bool = False
    sent: str | None = None

    def send(self, text: str) -> None:
        if self.fail:
            raise NotificationError("simulated webhook failure")
        self.sent = text


class DemoExplainer:
    """Stands in for the LLM. ``invent_figure`` simulates a model that makes up a saving."""

    def __init__(self, invent_figure: bool = False) -> None:
        self._invent = invent_figure

    def explain(self, facts: str) -> str:
        if self._invent:
            return "You could save INR 9,999.00 per month by deleting everything."
        return (
            "The report lists 3 confirmed findings and 1 potential finding. Confirmed savings "
            "are estimated at INR 870.00 per month across 2 findings. The virtual machine "
            "finding needs review by its owner."
        )


def demo_explainer(scenario: str, requested: bool) -> Explainer | None:
    if scenario == "llm-rejected":
        return DemoExplainer(invent_figure=True)
    return DemoExplainer() if requested else None


def demo_notifier(scenario: str) -> Notifier:
    return DemoNotifier(fail=scenario == "notify-failure")
