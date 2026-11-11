"""Unattached managed disks. State is read directly from Azure, so findings are CONFIRMED."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from ..models import Confidence, Evidence, Finding, FindingStatus
from .base import DetectionContext, DetectionResult, attribute_cost, required, text

CATEGORY = "unattached_disk"
RG = "resource-graph"


def detect_unattached_disks(
    rows: Sequence[Mapping[str, Any]], ctx: DetectionContext
) -> DetectionResult:
    out = DetectionResult()
    for row in rows:
        try:
            # Defence in depth: never trust the query filter alone.
            if text(row, "managedBy") or text(row, "diskState").lower() != "unattached":
                continue
            rid, name = required(row, "id"), required(row, "name")
            size = row.get("sizeGb")
            sku = text(row, "skuName") or "unknown"
            evidence = [
                Evidence(source=RG, metric="diskState", value="Unattached"),
                Evidence(source=RG, metric="managedBy", value="(none)"),
                Evidence(source=RG, metric="sku", value=sku),
                Evidence(
                    source=RG,
                    metric="sizeGb",
                    value=float(size) if size is not None else None,
                    unit="GB",
                ),
                Evidence(source=RG, metric="timeCreated", value=text(row, "timeCreated") or None),
            ]
            cost_ev, monthly = attribute_cost(ctx, rid, counts_as_savings=True)
            out.findings.append(
                Finding(
                    resource_id=rid,
                    name=name,
                    resource_type="microsoft.compute/disks",
                    resource_group=required(row, "resourceGroup"),
                    subscription_id=text(row, "subscriptionId") or ctx.subscription_id,
                    region=required(row, "location"),
                    category=CATEGORY,
                    status=FindingStatus.CONFIRMED,
                    reason=f"Managed disk is not attached to any VM ({sku}, {size} GB).",
                    evidence=evidence + cost_ev,
                    confidence=Confidence.HIGH,
                    monthly_cost=monthly,
                    recommended_action=(
                        "Confirm the disk is not needed (check snapshots/backups), then delete "
                        "it or snapshot and delete it. This tool never modifies resources."
                    ),
                    evidence_timestamp=ctx.now,
                )
            )
        except (KeyError, ValueError, ValidationError):
            out.errors.append(f"{CATEGORY}: skipped malformed row ({text(row, 'id') or '?'})")
    out.notes.append(
        "Unattached disks: how long a disk has been detached is not available from Resource "
        "Graph; a recently detached disk may be intentional."
    )
    return out
