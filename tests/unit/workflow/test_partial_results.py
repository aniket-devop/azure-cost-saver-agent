"""Failures must produce an explicit partial report, never a silent clean one."""

import json

import pytest

from azure_finops_agent.reporting import ReportStatus, assemble
from azure_finops_agent.workflow import ManualClock, StageStatus, run_workflow

from .fakes import (
    FakeCost,
    FakeGraph,
    FakeMonitor,
    TransientError,
    disk_row,
    fast_limits,
    ip_row,
    make_deps,
    rid,
    vm_row,
)

IDLE = rid("Microsoft.Compute/virtualMachines", "vm-idle")


def boom(exc=None):
    def hook():
        raise exc or TransientError("simulated outage")

    return hook


def build(tmp_path, *, graph_hooks=None, cost_hooks=None, monitor=None, **kw):
    graph = FakeGraph(
        disks=[disk_row("d1")],
        ips=[ip_row("ip1")],
        vms=[vm_row("vm-idle")],
        hooks=graph_hooks,
        truncated=kw.pop("truncated", None),
    )
    cost = FakeCost(
        total=500.0,
        per_resource={rid("Microsoft.Compute/disks", "d1"): 120.0},
        hooks=cost_hooks,
    )
    mon = monitor or FakeMonitor({IDLE: (1.0, 5.0)})
    return make_deps(tmp_path, graph=graph, cost=cost, monitor=mon, **kw)


def test_a_failed_disk_collector_is_reported_and_the_rest_still_runs(tmp_path):
    result = run_workflow(build(tmp_path, graph_hooks={"disks": boom()}))
    assert result.stage("collect_disks").status is StageStatus.FAILED
    assert result.stage("detect_disks").status is StageStatus.SKIPPED  # never run on "no data"
    assert result.stage("detect_public_ips").status is StageStatus.OK
    assert {f.name for f in result.report.findings} == {"ip1", "vm-idle"}
    assert result.partial and result.exit_code == 3
    assert result.summary.status is ReportStatus.PARTIAL
    assert any("unattached disks collection failed" in e for e in result.report.errors)
    assert any("Unattached disks were not analysed" in x for x in result.report.limitations)
    assert (tmp_path / "report.md").exists() and (tmp_path / "report.json").exists()


@pytest.mark.parametrize(
    ("hook_kind", "key", "stage"),
    [
        ("graph", "disks", "collect_disks"),
        ("graph", "ips", "collect_public_ips"),
        ("graph", "vms", "collect_vms"),
        ("cost", "total", "collect_total_cost"),
        ("cost", "resource", "collect_resource_costs"),
    ],
)
def test_each_collector_can_fail_alone_without_stopping_the_run(tmp_path, hook_kind, key, stage):
    hooks = {key: boom()}
    deps = build(
        tmp_path,
        graph_hooks=hooks if hook_kind == "graph" else None,
        cost_hooks=hooks if hook_kind == "cost" else None,
    )
    result = run_workflow(deps)
    failed = [s.name for s in result.stages if s.status is StageStatus.FAILED]
    assert failed == [stage]
    assert result.partial and result.exit_code == 3
    assert result.report is not None and result.paths is not None


def test_when_everything_fails_the_report_still_exists_and_says_so(tmp_path):
    deps = build(
        tmp_path,
        graph_hooks={k: boom() for k in ("disks", "ips", "vms")},
        cost_hooks={k: boom() for k in ("total", "resource")},
    )
    result = run_workflow(deps)
    assert result.report.findings == []
    assert result.partial and result.exit_code == 3
    assert len(result.report.errors) == 5  # one explicit error per failed collector
    data = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert data["report_status"] == "partial"  # an empty report is never presented as "clean"
    assert assemble.NO_RESOURCE_COSTS in result.report.limitations
    assert assemble.NO_TOTAL_COST in result.report.limitations


def test_resource_cost_failure_leaves_costs_unknown_not_zero(tmp_path):
    result = run_workflow(build(tmp_path, cost_hooks={"resource": boom()}))
    disk = next(f for f in result.report.findings if f.name == "d1")
    assert disk.monthly_cost.amount is None
    assert result.summary.confirmed_savings == ()
    assert result.partial


def test_no_cost_rows_is_a_limitation_not_an_error(tmp_path):
    deps = build(tmp_path)
    deps.clients.cost.total = None  # Azure returns no rows (billing lag)
    result = run_workflow(deps)
    assert result.stage("collect_total_cost").status is StageStatus.OK
    assert assemble.NO_TOTAL_COST in result.report.limitations
    assert not result.partial and result.exit_code == 0


def test_one_vm_metrics_failure_is_recorded_for_that_vm_only(tmp_path):
    bad = rid("Microsoft.Compute/virtualMachines", "vm-bad")

    def hook(resource_id):
        if resource_id == bad:
            raise ValueError("metrics endpoint rejected the request")

    graph = FakeGraph(vms=[vm_row("vm-idle"), vm_row("vm-bad")])
    deps = make_deps(
        tmp_path, graph=graph, cost=FakeCost(), monitor=FakeMonitor({IDLE: (1.0, 5.0)}, hook=hook)
    )
    result = run_workflow(deps)
    assert {f.name for f in result.report.findings} == {"vm-idle"}
    assert any(bad in e and "metrics unavailable" in e for e in result.report.errors)
    assert result.partial
    assert "metrics endpoint rejected" not in json.dumps(result.report.errors)  # type name only


def test_vm_not_collected_is_an_explicit_error_not_silently_clean(tmp_path):
    # A VM whose id the collector never queried must surface as an error in the detector.
    from azure_finops_agent.collectors.errors import AzureDataError
    from azure_finops_agent.workflow.detect import make_cpu_provider

    with pytest.raises(AzureDataError, match="not collected"):
        make_cpu_provider({})("/subscriptions/x/vm")


def test_truncated_resource_graph_results_add_a_limitation(tmp_path):
    result = run_workflow(build(tmp_path, truncated={"disks"}))
    assert any("unattached disks were truncated" in x for x in result.report.limitations)
    assert not result.partial  # incomplete list is a limitation; no stage failed


def test_transient_failures_are_retried_with_the_injected_clock(tmp_path):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise TransientError("503")

    clock = ManualClock()
    result = run_workflow(build(tmp_path, graph_hooks={"disks": flaky}, clock=clock))
    assert result.stage("collect_disks").status is StageStatus.OK
    assert calls["n"] == 3
    assert len(clock.sleeps) == 2  # two back-offs, taken on the fake clock (no real waiting)
    assert not result.partial


def test_exhausted_retries_become_a_failed_stage_with_a_safe_message(tmp_path):
    clock = ManualClock()
    result = run_workflow(build(tmp_path, graph_hooks={"vms": boom()}, clock=clock))
    stage = result.stage("collect_vms")
    assert stage.status is StageStatus.FAILED
    assert stage.detail == "resource-graph query: TransientError"
    assert len(clock.sleeps) == 3  # 4 attempts, 3 waits


def test_run_budget_exceeded_skips_remaining_stages_explicitly(tmp_path):
    clock = ManualClock()
    limits = fast_limits(run_budget_s=100)
    deps = build(
        tmp_path, cost_hooks={"total": lambda: clock.advance(500)}, clock=clock, limits=limits
    )
    result = run_workflow(deps)
    for name in ("detect_disks", "detect_public_ips", "detect_vms"):
        stage = result.stage(name)
        assert stage.status is StageStatus.SKIPPED and "budget" in stage.detail
    assert result.report.findings == []
    assert result.partial and any(
        "run time budget of 100s exceeded" in e for e in result.report.errors
    )
    assert result.stage("write_reports").status is StageStatus.OK  # the partial report is delivered
    assert (tmp_path / "report.md").exists()


def test_metrics_time_budget_stops_querying_more_vms(tmp_path):
    clock = ManualClock()
    vms = [vm_row(f"vm{i}") for i in range(5)]
    monitor = FakeMonitor(hook=lambda _rid: clock.advance(60))
    deps = make_deps(
        tmp_path,
        graph=FakeGraph(vms=vms),
        cost=FakeCost(),
        monitor=monitor,
        clock=clock,
        limits=fast_limits(max_workers=1, metrics_budget_s=100),
    )
    result = run_workflow(deps)
    assert len(monitor.recorder.calls) == 2  # t=0 and t=60 start; t=120 is over the 100s budget
    budget_errors = [e for e in result.report.errors if "time budget exceeded" in e]
    assert len(budget_errors) == 3 and result.partial


def test_assemble_failure_is_fatal_but_clean(tmp_path, monkeypatch):
    def broken(**_):
        raise RuntimeError("bug")

    monkeypatch.setattr("azure_finops_agent.workflow.graph.assemble_report", broken)
    result = run_workflow(build(tmp_path))
    assert result.report is None and result.exit_code == 1
    assert result.stage("assemble").status is StageStatus.FAILED
    assert result.stage("write_reports").status is StageStatus.SKIPPED
    assert (tmp_path / "run_summary.json").exists()  # the failure itself is still recorded
