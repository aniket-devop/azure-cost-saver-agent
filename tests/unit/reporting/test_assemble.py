from datetime import datetime
from decimal import Decimal

import pytest

from azure_finops_agent.collectors.costs import ResourceCosts
from azure_finops_agent.detectors import DetectionResult
from azure_finops_agent.models import (
    Confidence,
    CostBasis,
    Evidence,
    Finding,
    FindingStatus,
    MonthlyCost,
)
from azure_finops_agent.reporting import ReportInvariantError, assemble_report, render_json
from azure_finops_agent.reporting import assemble as asm
from azure_finops_agent.reporting.invariants import POTENTIAL_ONLY_CATEGORIES

from .sample_data import DISK_ORPHAN, NOW, SUB, VM_BUILD, build_sample_report, rid


def finding(
    resource_id=DISK_ORPHAN,
    category="unattached_disk",
    status=FindingStatus.CONFIRMED,
    amount="10.00",
    name="d1",
):
    cost = (
        MonthlyCost(amount=Decimal(amount), currency="INR", basis=CostBasis.ACTUAL_COST)
        if amount is not None
        else MonthlyCost(amount=None, currency=None, basis=CostBasis.UNAVAILABLE)
    )
    return Finding(
        resource_id=resource_id, name=name, resource_type="t", resource_group="rg",
        subscription_id=SUB, region="r", category=category, status=status, reason="why",
        evidence=[Evidence(source="s", metric="m", value=1.0)], confidence=Confidence.HIGH,
        monthly_cost=cost, recommended_action="act", evidence_timestamp=NOW,
    )  # fmt: skip


def build(results, **kw):
    kw.setdefault("cost_summary", None)
    kw.setdefault("costs", ResourceCosts({}, "INR", 30, "a", "b", False))
    return assemble_report(subscription_id=SUB, generated_at=NOW, results=results, **kw)


def test_merges_errors_and_notes_from_every_detector():
    a = DetectionResult([finding()], ["e2"], ["n2"])
    b = DetectionResult([], ["e1"], ["n1", "n2"])
    r = build([a, b])
    assert r.errors == ["e1", "e2"]
    assert r.limitations[:2] == ["n1", "n2"] or "n1" in r.limitations
    assert r.limitations.count("n2") == 1


def test_output_does_not_depend_on_detector_order():
    results = [
        DetectionResult([finding(rid("Microsoft.Compute/disks", f"d{i}"), name=f"d{i}")])
        for i in range(6)
    ]
    shuffled = [results[i] for i in (3, 0, 5, 2, 4, 1)]
    assert render_json(build(results)) == render_json(build(shuffled))


def test_confirmed_sorted_before_potential():
    vm = finding(VM_BUILD, "underutilized_vm", FindingStatus.POTENTIAL, None, "vm")
    r = build([DetectionResult([vm, finding()])])
    assert [f.status for f in r.findings] == [FindingStatus.CONFIRMED, FindingStatus.POTENTIAL]


def test_duplicate_finding_dropped_and_reported_not_double_counted():
    r = build([DetectionResult([finding(), finding(DISK_ORPHAN.upper())])])
    assert len(r.findings) == 1
    assert any("duplicate finding dropped" in e for e in r.errors)
    assert r.potential_savings_by_currency() == {"INR": Decimal("10.00")}


def test_vm_finding_cannot_be_confirmed():
    bad = finding(VM_BUILD, "underutilized_vm", FindingStatus.CONFIRMED, None)
    with pytest.raises(ReportInvariantError):
        build([DetectionResult([bad])])


def test_potential_only_categories_match_detector():
    from azure_finops_agent.detectors import vms

    assert vms.CATEGORY in POTENTIAL_ONLY_CATEGORIES


@pytest.mark.parametrize(
    ("costs", "summary", "expected"),
    [
        (None, True, asm.NO_RESOURCE_COSTS),
        (ResourceCosts({}, "INR", 30, "a", "b", True), True, asm.PARTIAL_RESOURCE_COSTS),
        (ResourceCosts({}, "INR", 30, "a", "b", False), None, asm.NO_TOTAL_COST),
    ],
)
def test_missing_cost_data_becomes_a_limitation(costs, summary, expected):
    cs = None
    if summary is True:
        from azure_finops_agent.models import CostSummary

        cs = CostSummary(total=Decimal(1), currency="INR", start_date="a", end_date="b")
    r = build([], costs=costs, cost_summary=cs)
    assert expected in r.limitations


def test_complete_costs_add_no_cost_limitations():
    from azure_finops_agent.models import CostSummary

    cs = CostSummary(total=Decimal(1), currency="INR", start_date="a", end_date="b")
    r = build([], cost_summary=cs)
    assert r.limitations == []


def test_naive_generated_at_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        assemble_report(
            subscription_id=SUB, generated_at=datetime(2026, 1, 1), cost_summary=None, results=[]
        )


def test_sample_pipeline_uses_real_detectors():
    r = build_sample_report()
    cats = sorted(f.category for f in r.findings)
    assert cats == [
        "unattached_disk", "unattached_disk", "unattached_public_ip", "unattached_public_ip",
        "underutilized_vm", "underutilized_vm",
    ]  # fmt: skip
    assert all(
        f.status is FindingStatus.POTENTIAL for f in r.findings if f.category == "underutilized_vm"
    )
    assert any("vm-metrics-fail-03" in e for e in r.errors)
