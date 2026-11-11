import json
from decimal import Decimal

import pytest

from azure_finops_agent.models import Evidence, FindingStatus, Report
from azure_finops_agent.reporting import (
    ReportInvariantError,
    ReportParseError,
    parse_report_json,
    render_json,
)

from .sample_data import NOW, SUB, VM_BUILD, build_sample_report
from .test_assemble import build, finding


def test_output_is_canonical_text():
    text = render_json(build_sample_report())
    assert text.endswith("}\n") and "\r" not in text
    assert text.isascii()
    data = json.loads(text)
    assert list(data) == sorted(data)
    assert data["generated_at"] == "2026-11-11T12:00:00Z"
    assert data["report_status"] == "partial"


def test_decimals_are_strings_and_unknown_is_null_not_zero():
    data = json.loads(render_json(build_sample_report()))
    costs = {f["name"]: f["monthly_cost"] for f in data["findings"]}
    assert costs["orphan-data-disk-01"] == {
        "amount": "842.40", "basis": "actual_cost", "currency": "INR"
    }  # fmt: skip
    assert costs["old-backup-disk"] == {"amount": None, "basis": "unavailable", "currency": None}
    assert costs["vm-dev-build-01"]["amount"] is None


def test_same_input_same_bytes():
    assert render_json(build_sample_report()) == render_json(build_sample_report())


def test_round_trip_through_report_model():
    original = build_sample_report()
    assert parse_report_json(render_json(original)) == original


def test_non_finite_evidence_becomes_null():
    f = finding().model_copy(
        update={"evidence": [Evidence(source="s", metric="m", value=float("nan"))]}
    )
    data = json.loads(render_json(build([_result(f)])))
    assert data["findings"][0]["evidence"][0]["value"] is None


def _result(f):
    from azure_finops_agent.detectors import DetectionResult

    return DetectionResult([f])


def test_non_utc_timestamps_are_normalised():
    from datetime import datetime, timedelta, timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    r = Report(generated_at=datetime(2026, 11, 11, 17, 30, tzinfo=ist), subscription_id=SUB,
               cost_summary=None, findings=[])  # fmt: skip
    assert json.loads(render_json(r))["generated_at"] == "2026-11-11T12:00:00Z"
    assert r.generated_at == NOW


def test_tampered_summary_is_rejected():
    data = json.loads(render_json(build_sample_report()))
    data["summary"]["confirmed_monthly_savings_estimate"][0]["amount"] = "999999.00"
    with pytest.raises(ReportParseError, match="derived field 'summary'"):
        parse_report_json(json.dumps(data))


def test_tampered_status_is_rejected():
    data = json.loads(render_json(build_sample_report()))
    data["report_status"] = "complete"
    with pytest.raises(ReportParseError, match="report_status"):
        parse_report_json(json.dumps(data))


@pytest.mark.parametrize("bad", ["not json", "[]", '{"findings": 5}'])
def test_invalid_documents_are_rejected(bad):
    with pytest.raises(ReportParseError):
        parse_report_json(bad)


def test_confirmed_vm_in_file_is_rejected_on_parse():
    data = json.loads(render_json(build_sample_report()))
    for f in data["findings"]:
        if f["category"] == "underutilized_vm":
            f["status"] = "confirmed"
    with pytest.raises(ReportParseError):
        parse_report_json(json.dumps(data))


def test_render_refuses_confirmed_vm():
    bad = finding(VM_BUILD, "underutilized_vm", FindingStatus.CONFIRMED, None)
    r = Report(generated_at=NOW, subscription_id=SUB, cost_summary=None, findings=[bad])
    with pytest.raises(ReportInvariantError):
        render_json(r)


def test_decimal_never_scientific():
    f = finding(amount="1E+2")
    assert f.monthly_cost.amount == Decimal("1E+2")
    data = json.loads(render_json(build([_result(f)])))
    assert data["findings"][0]["monthly_cost"]["amount"] == "100"
