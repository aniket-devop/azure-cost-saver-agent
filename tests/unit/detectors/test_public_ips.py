from decimal import Decimal

from azure_finops_agent.detectors import DetectionContext, detect_unattached_public_ips
from azure_finops_agent.models import Confidence, FindingStatus

from .conftest import NOW, SUB, costs, rid

IP = rid("Microsoft.Network/publicIPAddresses", "idle-ip")


def row(**over):
    base = {
        "id": IP,
        "name": "idle-ip",
        "resourceGroup": "rg1",
        "subscriptionId": SUB,
        "location": "centralindia",
        "skuName": "Standard",
        "allocation": "Static",
        "ipAddress": "20.1.2.3",
        "ipConfigId": "",
        "natGatewayId": "",
    }
    base.update(over)
    return base


def test_unattached_ip_is_confirmed(ctx):
    (f,) = detect_unattached_public_ips([row()], ctx).findings
    assert f.status is FindingStatus.CONFIRMED and f.confidence is Confidence.HIGH
    assert f.resource_id == IP and f.evidence_timestamp == NOW
    assert any(e.metric == "ipConfiguration" for e in f.evidence)


def test_attached_ips_are_ignored(ctx):
    rows = [row(ipConfigId="/nic/ipconfig1"), row(natGatewayId="/natgw/1")]
    assert detect_unattached_public_ips(rows, ctx).findings == []


def test_unallocated_dynamic_ip_has_lower_confidence(ctx):
    (f,) = detect_unattached_public_ips([row(ipAddress="", allocation="Dynamic")], ctx).findings
    assert f.confidence is Confidence.MEDIUM
    assert next(e for e in f.evidence if e.metric == "ipAddress").value == "(not allocated)"


def test_zero_actual_cost_is_reported_honestly():
    ctx = DetectionContext(SUB, NOW, costs(**{IP: 0}))
    (f,) = detect_unattached_public_ips([row()], ctx).findings
    assert f.monthly_cost.amount == Decimal("0.00")


def test_actual_cost_used_when_available():
    ctx = DetectionContext(SUB, NOW, costs(**{IP: 280}))
    (f,) = detect_unattached_public_ips([row()], ctx).findings
    assert f.monthly_cost.amount == Decimal("280.00")


def test_malformed_row_reported(ctx):
    res = detect_unattached_public_ips([row(name="")], ctx)
    assert res.findings == [] and len(res.errors) == 1
