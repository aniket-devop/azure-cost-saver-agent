from datetime import timedelta

from azure_finops_agent.collectors.errors import AzureDataError
from azure_finops_agent.collectors.monitor import CpuStats
from azure_finops_agent.detectors import DetectionContext, detect_underutilized_vms
from azure_finops_agent.models import Confidence, CostBasis, FindingStatus

from .conftest import NOW, SUB, costs, rid

VM = rid("Microsoft.Compute/virtualMachines", "vm1")


def row(**over):
    base = {
        "id": VM,
        "name": "vm1",
        "resourceGroup": "rg1",
        "subscriptionId": SUB,
        "location": "centralindia",
        "vmSize": "Standard_D4s_v5",
        "powerState": "PowerState/running",
        "timeCreated": "2026-01-01T00:00:00Z",
    }
    base.update(over)
    return base


def stats(avg=2.0, mx=10.0, points=168):
    return CpuStats(avg, mx, points, 168, NOW - timedelta(days=7), NOW)


def provider(s):
    return lambda _rid: s


def run(rows, s=None, ctx=None, **kw):
    ctx = ctx or DetectionContext(SUB, NOW)
    return detect_underutilized_vms(rows, ctx, provider(s or stats()), **kw)


def test_idle_vm_is_potential_with_evidence():
    (f,) = run([row()]).findings
    assert f.status is FindingStatus.POTENTIAL and f.confidence is Confidence.MEDIUM
    metrics = {e.metric for e in f.evidence}
    assert {"cpu_average_pct", "cpu_max_pct", "hourly_datapoints", "vmSize"} <= metrics
    assert "2.0%" in f.reason and "10.0%" in f.reason
    assert any("not evaluated" in n for n in run([row()]).notes)


def test_vm_never_claims_savings_even_with_cost_data():
    ctx = DetectionContext(SUB, NOW, costs(**{VM: 9000}))
    (f,) = run([row()], ctx=ctx).findings
    assert f.monthly_cost.amount is None and f.monthly_cost.basis is CostBasis.UNAVAILABLE
    assert any(e.source == "cost-management" for e in f.evidence)  # shown as evidence only


def test_spiky_vm_is_not_flagged_even_with_low_average():
    assert run([row()], stats(avg=2.0, mx=95.0)).findings == []


def test_busy_vm_not_flagged():
    assert run([row()], stats(avg=40.0, mx=60.0)).findings == []


def test_threshold_boundaries_are_exclusive():
    assert run([row()], stats(avg=5.0, mx=10.0)).findings == []
    assert run([row()], stats(avg=2.0, mx=30.0)).findings == []


def test_custom_thresholds():
    assert len(run([row()], stats(avg=8.0, mx=10.0), cpu_avg_threshold=10).findings) == 1


def test_missing_metrics_never_flag_and_are_noted():
    res = run([row()], CpuStats(None, None, 0, 168, NOW, NOW))
    assert res.findings == [] and any("skipped: fewer than 80%" in n for n in res.notes)


def test_sparse_metrics_never_flag():
    res = run([row()], stats(points=40))
    assert res.findings == [] and any("datapoints" in n for n in res.notes)


def test_partial_coverage_lowers_confidence():
    (f,) = run([row()], stats(points=140)).findings  # 83%
    assert f.confidence is Confidence.LOW


def test_new_vm_is_skipped():
    created = (NOW - timedelta(days=2)).isoformat()
    res = run([row(timeCreated=created)])
    assert res.findings == [] and any("younger than 7 days" in n for n in res.notes)


def test_stopped_and_deallocated_vms_are_skipped():
    calls = []
    rows = [row(powerState="PowerState/deallocated"), row(powerState="PowerState/stopped")]
    res = detect_underutilized_vms(
        rows, DetectionContext(SUB, NOW), lambda r: calls.append(r) or stats()
    )
    assert res.findings == [] and calls == []
    assert any("2 VM(s) not in running state" in n for n in res.notes)


def test_unknown_power_state_is_still_analysed():
    assert len(run([row(powerState="")]).findings) == 1


def test_metric_failure_is_isolated_per_vm():
    def flaky(resource_id):
        if resource_id.endswith("bad"):
            raise AzureDataError("azure-monitor metrics", "HttpResponseError", status_code=403)
        return stats()

    rows = [row(id=VM + "bad", name="bad"), row()]
    res = detect_underutilized_vms(rows, DetectionContext(SUB, NOW), flaky)
    assert len(res.findings) == 1 and len(res.errors) == 1
    assert res.errors[0].startswith("underutilized_vm: metrics unavailable for")


def test_malformed_row_reported():
    res = run([row(name="")])
    assert res.findings == [] and len(res.errors) == 1


def test_bounded_execution():
    calls = []
    rows = [row(id=f"{VM}{i}", name=f"vm{i}") for i in range(10)]
    res = detect_underutilized_vms(
        rows, DetectionContext(SUB, NOW), lambda r: calls.append(r) or stats(), max_vms=3
    )
    assert len(calls) == 3 and any("first 3 of 10" in n for n in res.notes)
