"""Unattached public IP addresses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from ..models import Confidence, Evidence, Finding, FindingStatus
from .base import DetectionContext, DetectionResult, attribute_cost, required, text

CATEGORY = "unattached_public_ip"
RG = "resource-graph"


def detect_unattached_public_ips(
    rows: Sequence[Mapping[str, Any]], ctx: DetectionContext
) -> DetectionResult:
    out = DetectionResult()
    for row in rows:
        try:
            if text(row, "ipConfigId") or text(row, "natGatewayId"):
                continue  # attached to a NIC, load balancer, gateway or NAT gateway
            rid, name = required(row, "id"), required(row, "name")
            sku = text(row, "skuName") or "unknown"
            allocation = text(row, "allocation") or "unknown"
            address = text(row, "ipAddress")
            evidence = [
                Evidence(source=RG, metric="ipConfiguration", value="(none)"),
                Evidence(source=RG, metric="natGateway", value="(none)"),
                Evidence(source=RG, metric="sku", value=sku),
                Evidence(source=RG, metric="allocationMethod", value=allocation),
                Evidence(source=RG, metric="ipAddress", value=address or "(not allocated)"),
            ]
            cost_ev, monthly = attribute_cost(ctx, rid, counts_as_savings=True)
            out.findings.append(
                Finding(
                    resource_id=rid,
                    name=name,
                    resource_type="microsoft.network/publicipaddresses",
                    resource_group=required(row, "resourceGroup"),
                    subscription_id=text(row, "subscriptionId") or ctx.subscription_id,
                    region=required(row, "location"),
                    category=CATEGORY,
                    status=FindingStatus.CONFIRMED,
                    reason=(
                        f"Public IP is not associated with any NIC, load balancer or NAT gateway "
                        f"({sku}, {allocation})."
                    ),
                    evidence=evidence + cost_ev,
                    # An unallocated dynamic IP exists but may carry no charge.
                    confidence=Confidence.HIGH if address else Confidence.MEDIUM,
                    monthly_cost=monthly,
                    recommended_action=(
                        "Confirm nothing (DNS records, allow-lists) depends on this address, "
                        "then delete it. This tool never modifies resources."
                    ),
                    evidence_timestamp=ctx.now,
                )
            )
        except (KeyError, ValueError, ValidationError):
            out.errors.append(f"{CATEGORY}: skipped malformed row ({text(row, 'id') or '?'})")
    out.notes.append(
        "Public IPs: billing depends on SKU and allocation; savings are shown only when "
        "Cost Management has charges for the resource."
    )
    return out
