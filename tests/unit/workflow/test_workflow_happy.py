"""The graph must produce exactly what composing Phase 2, 3 and 4 by hand produces."""

import json

import pytest

from azure_finops_agent.collectors.costs import get_resource_costs, get_total_cost
from azure_finops_agent.collectors.graph import query_all
from azure_finops_agent.collectors.monitor import get_cpu_stats
from azure_finops_agent.config import Settings
from azure_finops_agent.detectors import (
    DetectionContext,
    detect_unattached_disks,
    detect_unattached_public_ips,
    detect_underutilized_vms,
    queries,
)
from azure_finops_agent.reporting import (
    assemble_report,
    parse_report_json,
    render_json,
    render_markdown,
)
from azure_finops_agent.workflow import ManualClock, StageStatus, build_workflow, run_workflow

from .fakes import (
    SUB,
    FakeCost,
    FakeGraph,
    FakeMonitor,
    disk_row,
    ip_row,
    make_deps,
    rid,
    vm_row,
)

IDLE = rid("Microsoft.Compute/virtualMachines", "vm-idle")


def fakes():
    graph = FakeGraph(
        disks=[disk_row("d1"), disk_row("d2")],
        ips=[ip_row("ip1")],
        vms=[vm_row("vm-idle"), vm_row("vm-busy"), vm_row("vm-off", "PowerState/deallocated")],
    )
    cost = FakeCost(
        total=1000.0,
        per_resource={
            rid("Microsoft.Compute/disks", "d1"): 300.0,
            rid("Microsoft.Network/publicIPAddresses", "ip1"): 90.0,
        },
    )
    monitor = FakeMonitor({IDLE: (1.0, 8.0)})
    return graph, cost, monitor


def direct_report():
    """Phase 2 -> 3 -> 4 composed by hand, sequentially, with fresh fakes."""
    graph, cost, monitor = fakes()
    clock = ManualClock()
    now = clock.now()
    costs = get_resource_costs(cost, SUB, days=30, now=now, sleep=clock.sleep)
    total = get_total_cost(cost, SUB, days=7, now=now, sleep=clock.sleep)
    rows = {
        k: query_all(graph, SUB, q, sleep=clock.sleep).rows
        for k, q in (("d", queries.DISKS), ("i", queries.PUBLIC_IPS), ("v", queries.VMS))
    }
    ctx = DetectionContext(SUB, now, costs)

    def cpu(resource_id):
        return get_cpu_stats(monitor, resource_id, lookback_days=7, now=now, sleep=clock.sleep)

    results = [
        detect_unattached_disks(rows["d"], ctx),
        detect_unattached_public_ips(rows["i"], ctx),
        detect_underutilized_vms(rows["v"], ctx, cpu, lookback_days=7),
    ]
    return assemble_report(
        subscription_id=SUB, generated_at=now, cost_summary=total, results=results, costs=costs
    )


def test_graph_output_is_byte_identical_to_composing_phases_2_3_4_by_hand(tmp_path):
    graph, cost, monitor = fakes()
    result = run_workflow(make_deps(tmp_path, graph=graph, cost=cost, monitor=monitor))
    expected = direct_report()
    assert (tmp_path / "report.json").read_text(encoding="utf-8") == render_json(expected)
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == render_markdown(expected)
    assert result.report == expected
    assert result.exit_code == 0 and not result.partial


def test_happy_path_findings_and_savings_come_from_cost_data_not_constants(tmp_path):
    graph, cost, monitor = fakes()
    result = run_workflow(make_deps(tmp_path, graph=graph, cost=cost, monitor=monitor))
    assert result.summary is not None
    by_name = {f.name: f for f in result.report.findings}
    assert set(by_name) == {"d1", "d2", "ip1", "vm-idle"}
    assert str(by_name["d1"].monthly_cost.amount) == "300.00"
    assert str(by_name["ip1"].monthly_cost.amount) == "90.00"
    assert by_name["d2"].monthly_cost.amount is None  # no cost row: unknown, never a guess
    assert by_name["vm-idle"].monthly_cost.amount is None  # CPU hint only: no savings claimed
    assert [(t.currency, str(t.amount)) for t in result.summary.confirmed_savings] == [
        ("INR", "390.00")
    ]


def test_report_json_round_trips_through_the_phase4_parser(tmp_path):
    graph, cost, monitor = fakes()
    run_workflow(make_deps(tmp_path, graph=graph, cost=cost, monitor=monitor))
    parse_report_json((tmp_path / "report.json").read_text(encoding="utf-8"))


def test_all_stages_ok_and_listed_in_canonical_order(tmp_path):
    graph, cost, monitor = fakes()
    result = run_workflow(make_deps(tmp_path, graph=graph, cost=cost, monitor=monitor))
    names = [s.name for s in result.stages]
    assert names == [
        "collect_total_cost",
        "collect_resource_costs",
        "collect_disks",
        "collect_public_ips",
        "collect_vms",
        "detect_disks",
        "detect_public_ips",
        "detect_vms",
        "assemble",
        "write_reports",
        "explain",
        "notify",
        "finalize",
    ]
    optional = {"explain", "notify"}
    assert all(s.status is StageStatus.OK for s in result.stages if s.name not in optional)
    assert all(result.stage(n).status is StageStatus.SKIPPED for n in optional)


def test_run_summary_file_matches_the_result(tmp_path):
    graph, cost, monitor = fakes()
    result = run_workflow(make_deps(tmp_path, graph=graph, cost=cost, monitor=monitor))
    data = json.loads((tmp_path / "run_summary.json").read_text(encoding="utf-8"))
    assert data["report_status"] == "complete" and data["exit_code"] == result.exit_code == 0
    assert data["started_at"] == "2026-11-11T12:00:00Z"
    assert [s["name"] for s in data["stages"]][0] == "collect_total_cost"


def test_the_graph_topology_is_fixed_and_has_no_llm_or_tool_node(tmp_path):
    app = build_workflow(make_deps(tmp_path))
    drawn = app.get_graph()
    assert set(drawn.nodes) == {
        "__start__",
        "start",
        "collect_total_cost",
        "collect_resource_costs",
        "collect_disks",
        "collect_public_ips",
        "collect_vms",
        "collected",
        "detect_disks",
        "detect_public_ips",
        "detect_vms",
        "assemble",
        "write_reports",
        "explain",
        "notify",
        "finalize",
        "__end__",
    }
    edges = {(e.source, e.target) for e in drawn.edges}
    for collector in ("collect_disks", "collect_vms", "collect_total_cost"):
        assert ("start", collector) in edges and (collector, "collected") in edges
    assert not any(e.conditional for e in drawn.edges)  # fixed topology: no node picks the route


@pytest.mark.parametrize("lookback", [3, 14])
def test_settings_drive_the_windows_and_thresholds(tmp_path, lookback):
    graph, cost, monitor = fakes()
    settings = Settings(subscription_id=SUB, lookback_days=lookback, cpu_idle_threshold_pct=0.5)
    result = run_workflow(
        make_deps(tmp_path, graph=graph, cost=cost, monitor=monitor, settings=settings)
    )
    # idle VM averages 1.0% > 0.5% threshold, so it is no longer reported
    assert {f.name for f in result.report.findings} == {"d1", "d2", "ip1"}
