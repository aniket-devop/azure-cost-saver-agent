# Azure Cost Saver Report

> Read-only analysis. This tool only reads from Azure; it never creates, modifies, stops or deletes any resource. Savings below are estimates, not realised savings.

| Field | Value |
|---|---|
| Subscription | `11111111-1111-1111-1111-111111111111` |
| Generated (UTC) | 2026-11-11T12:00:00Z |
| Report status | PARTIAL (1 issue(s)) |
| Schema version | 1.0 |

> **Partial report.** Some data could not be collected or analysed, so findings may be incomplete. See Data collection issues below.

## Summary

| Metric | Value |
|---|---|
| Subscription spend | INR 18,654.32 (2026-11-04 to 2026-11-11) |
| Total findings | 6 |
| Confirmed findings | 4 |
| Potential findings (need human review) | 2 |
| Confirmed findings with unknown cost | 2 |
| Potential findings without a savings estimate | 2 |

### Estimated monthly savings (confirmed findings only)

| Currency | Estimated monthly savings | Findings counted |
|---|---|---|
| INR | INR 1,094.50 | 2 |

These are estimates, not realised savings. Nothing has been deleted or changed, and confirmed findings with unknown cost are not included.

Potential findings carry no savings figure and are not part of any total.

### Findings by category

| Category | Confirmed | Potential |
|---|---|---|
| Unattached managed disks | 2 | 0 |
| Unattached public IP addresses | 2 | 0 |
| Under-utilized virtual machines | 0 | 2 |

## Data collection issues

- underutilized_vm: metrics unavailable for /subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-finops-demo/providers/Microsoft.Compute/virtualMachines/vm-metrics-fail-03 (monitor metrics: Throttled)

## Findings

### Confirmed findings

#### Unattached managed disks (2)

##### C-1: old-backup-disk

| Field | Value |
|---|---|
| Resource ID | `/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-finops-demo/providers/Microsoft.Compute/disks/old-backup-disk` |
| Type | `microsoft.compute/disks` |
| Resource group | `rg-finops-demo` |
| Region | `centralindia` |
| Status | CONFIRMED |
| Confidence | HIGH |
| Estimated monthly savings | Unknown (no cost data for this resource) |
| Evidence collected (UTC) | 2026-11-11T12:00:00Z |

**Why it was flagged:** Managed disk is not attached to any VM (StandardSSD_LRS, 128 GB).

**Recommended action:** Confirm the disk is not needed (check snapshots/backups), then delete it or snapshot and delete it. This tool never modifies resources.

**Evidence**

| Source | Metric | Value | Window (UTC) |
|---|---|---|---|
| resource-graph | diskState | Unattached | - |
| resource-graph | managedBy | (none) | - |
| resource-graph | sku | StandardSSD_LRS | - |
| resource-graph | sizeGb | 128 GB | - |
| resource-graph | timeCreated | 2026-10-30T10:00:00Z | - |

##### C-2: orphan-data-disk-01

| Field | Value |
|---|---|
| Resource ID | `/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-finops-demo/providers/Microsoft.Compute/disks/orphan-data-disk-01` |
| Type | `microsoft.compute/disks` |
| Resource group | `rg-finops-demo` |
| Region | `centralindia` |
| Status | CONFIRMED |
| Confidence | HIGH |
| Estimated monthly savings | INR 842.40 per month (estimate; basis: trailing actual cost) |
| Evidence collected (UTC) | 2026-11-11T12:00:00Z |

**Why it was flagged:** Managed disk is not attached to any VM (Premium_LRS, 256 GB).

**Recommended action:** Confirm the disk is not needed (check snapshots/backups), then delete it or snapshot and delete it. This tool never modifies resources.

**Evidence**

| Source | Metric | Value | Window (UTC) |
|---|---|---|---|
| resource-graph | diskState | Unattached | - |
| resource-graph | managedBy | (none) | - |
| resource-graph | sku | Premium_LRS | - |
| resource-graph | sizeGb | 256 GB | - |
| resource-graph | timeCreated | 2026-03-02T08:15:00Z | - |
| cost-management | actual_cost_2026-10-12_to_2026-11-11 | 842.4 INR | - |

#### Unattached public IP addresses (2)

##### C-3: pip-legacy-gateway

| Field | Value |
|---|---|
| Resource ID | `/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-finops-demo/providers/Microsoft.Network/publicIPAddresses/pip-legacy-gateway` |
| Type | `microsoft.network/publicipaddresses` |
| Resource group | `rg-finops-demo` |
| Region | `centralindia` |
| Status | CONFIRMED |
| Confidence | HIGH |
| Estimated monthly savings | INR 252.10 per month (estimate; basis: trailing actual cost) |
| Evidence collected (UTC) | 2026-11-11T12:00:00Z |

**Why it was flagged:** Public IP is not associated with any NIC, load balancer or NAT gateway (Standard, Static).

**Recommended action:** Confirm nothing (DNS records, allow-lists) depends on this address, then delete it. This tool never modifies resources.

**Evidence**

| Source | Metric | Value | Window (UTC) |
|---|---|---|---|
| resource-graph | ipConfiguration | (none) | - |
| resource-graph | natGateway | (none) | - |
| resource-graph | sku | Standard | - |
| resource-graph | allocationMethod | Static | - |
| resource-graph | ipAddress | 20.198.10.25 | - |
| cost-management | actual_cost_2026-10-12_to_2026-11-11 | 252.1 INR | - |

##### C-4: pip-unused-dynamic

| Field | Value |
|---|---|
| Resource ID | `/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-finops-demo/providers/Microsoft.Network/publicIPAddresses/pip-unused-dynamic` |
| Type | `microsoft.network/publicipaddresses` |
| Resource group | `rg-finops-demo` |
| Region | `centralindia` |
| Status | CONFIRMED |
| Confidence | MEDIUM |
| Estimated monthly savings | Unknown (no cost data for this resource) |
| Evidence collected (UTC) | 2026-11-11T12:00:00Z |

**Why it was flagged:** Public IP is not associated with any NIC, load balancer or NAT gateway (Basic, Dynamic).

**Recommended action:** Confirm nothing (DNS records, allow-lists) depends on this address, then delete it. This tool never modifies resources.

**Evidence**

| Source | Metric | Value | Window (UTC) |
|---|---|---|---|
| resource-graph | ipConfiguration | (none) | - |
| resource-graph | natGateway | (none) | - |
| resource-graph | sku | Basic | - |
| resource-graph | allocationMethod | Dynamic | - |
| resource-graph | ipAddress | (not allocated) | - |

### Potential findings (review required)

#### Under-utilized virtual machines (2)

##### P-1: vm-dev-build-01

| Field | Value |
|---|---|
| Resource ID | `/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-finops-demo/providers/Microsoft.Compute/virtualMachines/vm-dev-build-01` |
| Type | `microsoft.compute/virtualmachines` |
| Resource group | `rg-finops-demo` |
| Region | `centralindia` |
| Status | POTENTIAL |
| Confidence | MEDIUM |
| Estimated monthly savings | Not estimated (potential finding; no defensible figure) |
| Evidence collected (UTC) | 2026-11-11T12:00:00Z |

**Why it was flagged:** CPU averaged 1.8% (threshold 5.0%) and peaked at 12.4% (threshold 30.0%) over 7 days.

**Recommended action:** Review the workload with its owner. If confirmed under-used, consider resizing or deallocating. Memory, network and disk I/O were not evaluated. This tool never modifies resources.

**Evidence**

| Source | Metric | Value | Window (UTC) |
|---|---|---|---|
| azure-monitor | cpu_average_pct | 1.84 % | 2026-11-04T12:00:00Z to 2026-11-11T12:00:00Z |
| azure-monitor | cpu_max_pct | 12.4 % | 2026-11-04T12:00:00Z to 2026-11-11T12:00:00Z |
| azure-monitor | hourly_datapoints | 168 of 168 expected | - |
| resource-graph | vmSize | Standard_D4s_v5 | - |
| resource-graph | powerState | PowerState/running | - |
| cost-management | actual_cost_2026-10-12_to_2026-11-11 | 3120.55 INR | - |

##### P-2: vm-test-api-02

| Field | Value |
|---|---|
| Resource ID | `/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-finops-demo/providers/Microsoft.Compute/virtualMachines/vm-test-api-02` |
| Type | `microsoft.compute/virtualmachines` |
| Resource group | `rg-finops-demo` |
| Region | `centralindia` |
| Status | POTENTIAL |
| Confidence | LOW |
| Estimated monthly savings | Not estimated (potential finding; no defensible figure) |
| Evidence collected (UTC) | 2026-11-11T12:00:00Z |

**Why it was flagged:** CPU averaged 3.9% (threshold 5.0%) and peaked at 22.0% (threshold 30.0%) over 7 days.

**Recommended action:** Review the workload with its owner. If confirmed under-used, consider resizing or deallocating. Memory, network and disk I/O were not evaluated. This tool never modifies resources.

**Evidence**

| Source | Metric | Value | Window (UTC) |
|---|---|---|---|
| azure-monitor | cpu_average_pct | 3.92 % | 2026-11-04T12:00:00Z to 2026-11-11T12:00:00Z |
| azure-monitor | cpu_max_pct | 22 % | 2026-11-04T12:00:00Z to 2026-11-11T12:00:00Z |
| azure-monitor | hourly_datapoints | 150 of 168 expected | - |
| resource-graph | vmSize | Standard_D2s_v5 | - |
| resource-graph | powerState | PowerState/running | - |
| cost-management | actual_cost_2026-10-12_to_2026-11-11 | 1480.2 INR | - |

## Assumptions

- Estimated monthly savings = the resource's trailing actual cost from Azure Cost Management, scaled to a 30-day month. It is an estimate of what removing the resource could save, not an amount that has been saved.
- Savings are estimated only where removing the resource removes its cost (unattached disks and public IPs). Potential findings carry no savings figure because resizing or deallocating saves only part of a VM's cost.
- A resource missing from the cost data is reported as Unknown, never as zero (cost data can lag 24-48 hours).
- Amounts are in the billing currency reported by Azure. No currency conversion is done and different currencies are never added together.
- Confirmed means the state was read directly from Azure (for example, a disk with no owner). Potential means it was inferred from metrics and needs review by the resource owner.
- Evidence timestamps record when the data was collected for this report.

## Limitations

- Public IPs: billing depends on SKU and allocation; savings are shown only when Cost Management has charges for the resource.
- Unattached disks: how long a disk has been detached is not available from Resource Graph; a recently detached disk may be intentional.
- VM detection uses CPU only (Percentage CPU, hourly). Memory, network and disk I/O are not evaluated, so findings are potential, not confirmed.
