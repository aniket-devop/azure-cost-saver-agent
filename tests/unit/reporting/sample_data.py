"""Realistic report built by running the real detectors on Resource Graph-shaped rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from azure_finops_agent.collectors.costs import ResourceCosts
from azure_finops_agent.collectors.errors import AzureDataError
from azure_finops_agent.collectors.monitor import CpuStats
from azure_finops_agent.detectors import (
    DetectionContext,
    detect_unattached_disks,
    detect_unattached_public_ips,
    detect_underutilized_vms,
)
from azure_finops_agent.models import CostSummary, Report
from azure_finops_agent.reporting import assemble_report

SUB = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
LOC = "centralindia"


def rid(kind: str, name: str, rg: str = "rg-finops-demo") -> str:
    return f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/{kind}/{name}"


DISK_ORPHAN = rid("Microsoft.Compute/disks", "orphan-data-disk-01")
DISK_BACKUP = rid("Microsoft.Compute/disks", "old-backup-disk")
DISK_ATTACHED = rid("Microsoft.Compute/disks", "web-os-disk")
IP_LEGACY = rid("Microsoft.Network/publicIPAddresses", "pip-legacy-gateway")
IP_DYNAMIC = rid("Microsoft.Network/publicIPAddresses", "pip-unused-dynamic")
VM_BUILD = rid("Microsoft.Compute/virtualMachines", "vm-dev-build-01")
VM_API = rid("Microsoft.Compute/virtualMachines", "vm-test-api-02")
VM_BUSY = rid("Microsoft.Compute/virtualMachines", "vm-prod-web-01")
VM_FAIL = rid("Microsoft.Compute/virtualMachines", "vm-metrics-fail-03")


def _disk(rid_: str, name: str, sku: str, size: int, owner: str = "", created: str = "") -> dict:
    return {
        "id": rid_,
        "name": name,
        "resourceGroup": "rg-finops-demo",
        "subscriptionId": SUB,
        "location": LOC,
        "skuName": sku,
        "sizeGb": size,
        "diskState": "Attached" if owner else "Unattached",
        "managedBy": owner,
        "timeCreated": created or "2026-03-02T08:15:00Z",
    }


def _ip(rid_: str, name: str, sku: str, alloc: str, address: str) -> dict:
    return {
        "id": rid_,
        "name": name,
        "resourceGroup": "rg-finops-demo",
        "subscriptionId": SUB,
        "location": LOC,
        "skuName": sku,
        "allocation": alloc,
        "ipAddress": address,
        "ipConfigId": "",
        "natGatewayId": "",
    }


def _vm(rid_: str, name: str, size: str) -> dict:
    return {
        "id": rid_,
        "name": name,
        "resourceGroup": "rg-finops-demo",
        "subscriptionId": SUB,
        "location": LOC,
        "vmSize": size,
        "powerState": "PowerState/running",
        "timeCreated": "2026-01-10T09:00:00Z",
    }


def _cpu(avg: float, mx: float, points: int) -> CpuStats:
    return CpuStats(avg, mx, points, 168, NOW - timedelta(days=7), NOW)


def resource_costs() -> ResourceCosts:
    amounts = {
        DISK_ORPHAN: "842.40",
        DISK_ATTACHED: "610.00",
        IP_LEGACY: "252.10",
        VM_BUILD: "3120.55",
        VM_API: "1480.20",
        VM_BUSY: "5210.00",
    }
    return ResourceCosts(
        amounts={k.lower(): Decimal(v) for k, v in amounts.items()},
        currency="INR",
        days=30,
        start_date="2026-10-12",
        end_date="2026-11-11",
        partial=False,
    )


def build_sample_report() -> Report:
    costs = resource_costs()
    ctx = DetectionContext(subscription_id=SUB, now=NOW, costs=costs)
    cpu = {
        VM_BUILD: _cpu(1.84, 12.4, 168),
        VM_API: _cpu(3.92, 22.0, 150),  # 89% coverage: usable but lower confidence
        VM_BUSY: _cpu(38.5, 91.0, 168),  # busy: must not be flagged
    }

    def provider(resource_id: str) -> CpuStats:
        if resource_id == VM_FAIL:
            raise AzureDataError("monitor metrics", "Throttled", status_code=429)
        return cpu[resource_id]

    disks = [
        _disk(DISK_ORPHAN, "orphan-data-disk-01", "Premium_LRS", 256),
        _disk(
            DISK_BACKUP, "old-backup-disk", "StandardSSD_LRS", 128, created="2026-10-30T10:00:00Z"
        ),
        _disk(DISK_ATTACHED, "web-os-disk", "Premium_LRS", 128, owner=VM_BUSY),
    ]
    ips = [
        _ip(IP_LEGACY, "pip-legacy-gateway", "Standard", "Static", "20.198.10.25"),
        _ip(IP_DYNAMIC, "pip-unused-dynamic", "Basic", "Dynamic", ""),
    ]
    vms = [
        _vm(VM_BUILD, "vm-dev-build-01", "Standard_D4s_v5"),
        _vm(VM_API, "vm-test-api-02", "Standard_D2s_v5"),
        _vm(VM_BUSY, "vm-prod-web-01", "Standard_D8s_v5"),
        _vm(VM_FAIL, "vm-metrics-fail-03", "Standard_B4ms"),
    ]
    results = [
        detect_unattached_disks(disks, ctx),
        detect_unattached_public_ips(ips, ctx),
        detect_underutilized_vms(vms, ctx, provider),
    ]
    return assemble_report(
        subscription_id=SUB,
        generated_at=NOW,
        cost_summary=CostSummary(
            total=Decimal("18654.32"),
            currency="INR",
            start_date="2026-11-04",
            end_date="2026-11-11",
        ),
        results=results,
        costs=costs,
    )
