from dataclasses import replace
from decimal import Decimal

from azure_finops_agent.detectors import DetectionContext, detect_unattached_disks
from azure_finops_agent.models import Confidence, CostBasis, FindingStatus

from .conftest import NOW, SUB, costs, rid

DISK = rid("Microsoft.Compute/disks", "idle-disk")


def row(**over):
    base = {
        "id": DISK,
        "name": "idle-disk",
        "resourceGroup": "rg1",
        "subscriptionId": SUB,
        "location": "centralindia",
        "skuName": "Premium_LRS",
        "sizeGb": 128,
        "diskState": "Unattached",
        "timeCreated": "2026-09-01T10:00:00.1234567Z",
        "managedBy": "",
    }
    base.update(over)
    return base


def test_finding_is_complete_and_traceable(ctx):
    res = detect_unattached_disks([row()], ctx)
    (f,) = res.findings
    assert f.resource_id == DISK and f.name == "idle-disk"
    assert f.resource_type == "microsoft.compute/disks"
    assert (f.resource_group, f.subscription_id, f.region) == ("rg1", SUB, "centralindia")
    assert f.status is FindingStatus.CONFIRMED and f.confidence is Confidence.HIGH
    assert f.evidence_timestamp == NOW
    assert {e.metric for e in f.evidence} >= {"diskState", "managedBy", "sku", "sizeGb"}
    assert "128 GB" in f.reason and "never modifies" in f.recommended_action


def test_no_cost_data_means_no_savings_claim(ctx):
    (f,) = detect_unattached_disks([row()], ctx).findings
    assert f.monthly_cost.amount is None and f.monthly_cost.basis is CostBasis.UNAVAILABLE


def test_actual_cost_becomes_defensible_savings():
    ctx = DetectionContext(SUB, NOW, costs(**{DISK: "512.5"}))
    (f,) = detect_unattached_disks([row()], ctx).findings
    assert f.monthly_cost.amount == Decimal("512.50")
    assert f.monthly_cost.currency == "INR" and f.monthly_cost.basis is CostBasis.ACTUAL_COST
    assert any(e.source == "cost-management" for e in f.evidence)


def test_cost_lookup_is_case_insensitive():
    ctx = DetectionContext(SUB, NOW, costs(**{DISK.upper(): 10}))
    (f,) = detect_unattached_disks([row()], ctx).findings
    assert f.monthly_cost.amount == Decimal("10.00")


def test_cost_normalised_to_30_days():
    c = replace(costs(**{DISK: 14}), days=7)
    (f,) = detect_unattached_disks([row()], DetectionContext(SUB, NOW, c)).findings
    assert f.monthly_cost.amount == Decimal("60.00")


def test_attached_or_other_state_disks_are_ignored(ctx):
    rows = [row(managedBy="/subscriptions/x/vm1"), row(diskState="Attached"), row(diskState="")]
    assert detect_unattached_disks(rows, ctx).findings == []


def test_malformed_rows_are_reported_not_fatal(ctx):
    res = detect_unattached_disks([row(id=""), row(location=None), row()], ctx)
    assert len(res.findings) == 1 and len(res.errors) == 2


def test_missing_size_is_tolerated(ctx):
    (f,) = detect_unattached_disks([row(sizeGb=None)], ctx).findings
    assert next(e for e in f.evidence if e.metric == "sizeGb").value is None


def test_limitation_note_always_present(ctx):
    assert any("how long" in n for n in detect_unattached_disks([], ctx).notes)


def test_resource_missing_from_cost_data_is_unknown_not_zero():
    ctx = DetectionContext(SUB, NOW, costs(**{"/subscriptions/x/other": 99}))
    (f,) = detect_unattached_disks([row()], ctx).findings
    assert f.monthly_cost.amount is None and f.monthly_cost.basis is CostBasis.UNAVAILABLE
    assert not any(e.source == "cost-management" for e in f.evidence)
