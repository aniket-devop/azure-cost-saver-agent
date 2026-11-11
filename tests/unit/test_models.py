from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from azure_finops_agent.models import (
    Confidence,
    CostBasis,
    Evidence,
    Finding,
    FindingStatus,
    MonthlyCost,
    Report,
)

SUB = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 11, 11, tzinfo=UTC)


def make_finding(**over: object) -> Finding:
    data: dict[str, object] = {
        "resource_id": f"/subscriptions/{SUB}/resourceGroups/rg/providers/"
        "Microsoft.Compute/disks/d1",
        "name": "d1",
        "resource_type": "microsoft.compute/disks",
        "resource_group": "rg",
        "subscription_id": SUB,
        "region": "centralindia",
        "category": "unattached_disk",
        "status": FindingStatus.CONFIRMED,
        "reason": "Disk has no owner (diskState=Unattached)",
        "evidence": [Evidence(source="resource-graph", metric="diskState", value="Unattached")],
        "confidence": Confidence.HIGH,
        "monthly_cost": MonthlyCost(
            amount=Decimal("10.5"), currency="INR", basis=CostBasis.ACTUAL_COST
        ),
        "recommended_action": "Review and delete if no longer needed",
        "evidence_timestamp": NOW,
    }
    data.update(over)
    return Finding.model_validate(data)


def test_valid_finding():
    assert make_finding().status is FindingStatus.CONFIRMED


def test_finding_requires_evidence():
    with pytest.raises(ValidationError):
        make_finding(evidence=[])


def test_finding_rejects_non_azure_id():
    with pytest.raises(ValidationError):
        make_finding(resource_id="disk-1")


def test_finding_rejects_naive_timestamp():
    with pytest.raises(ValidationError):
        make_finding(evidence_timestamp=datetime(2026, 11, 11))


def test_finding_is_frozen():
    f = make_finding()
    with pytest.raises(ValidationError):
        f.name = "other"


def test_negative_cost_rejected():
    with pytest.raises(ValidationError):
        MonthlyCost(amount=Decimal("-1"), currency="INR", basis=CostBasis.ACTUAL_COST)


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        make_finding(surprise="x")


def _report(*findings: Finding) -> Report:
    return Report(generated_at=NOW, subscription_id=SUB, cost_summary=None, findings=list(findings))


def test_savings_sum_is_deterministic_and_per_currency():
    usd = MonthlyCost(amount=Decimal("3"), currency="USD", basis=CostBasis.RETAIL_PRICE)
    none = MonthlyCost(amount=None, currency=None, basis=CostBasis.UNAVAILABLE)
    r = _report(
        make_finding(),
        make_finding(),
        make_finding(monthly_cost=usd),
        make_finding(monthly_cost=none),
    )
    assert r.potential_savings_by_currency() == {"INR": Decimal("21.0"), "USD": Decimal("3")}


def test_empty_report_has_no_savings():
    assert _report().potential_savings_by_currency() == {}


def test_report_json_roundtrip():
    r = _report(make_finding())
    assert Report.model_validate_json(r.model_dump_json()) == r
