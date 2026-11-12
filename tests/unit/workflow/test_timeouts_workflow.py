"""Hung Azure calls become explicit TIMED_OUT stages; the report is still delivered.

Timeouts use real (short) wall-clock waits because a blocked thread can only be abandoned in real
time; the call is blocked on an Event, so the outcome does not depend on machine speed.
"""

import threading
import time

import pytest

from azure_finops_agent.workflow import StageStatus, run_workflow

from .fakes import (
    FakeCost,
    FakeGraph,
    FakeMonitor,
    disk_row,
    fast_limits,
    ip_row,
    make_deps,
    rid,
    vm_row,
)

SHORT = 0.2


@pytest.fixture
def hang():
    release = threading.Event()
    yield lambda: release.wait(30)
    release.set()  # let abandoned worker threads finish at teardown


def test_hung_collector_times_out_and_the_rest_of_the_run_completes(tmp_path, hang):
    graph = FakeGraph(disks=[disk_row("d1")], ips=[ip_row("ip1")], hooks={"disks": hang})
    deps = make_deps(tmp_path, graph=graph, limits=fast_limits(collector_timeout_s=SHORT))
    started = time.monotonic()
    result = run_workflow(deps)
    assert time.monotonic() - started < 5  # the hung call did not hold the run hostage
    stage = result.stage("collect_disks")
    assert stage.status is StageStatus.TIMED_OUT and stage.detail == "timed out after 0.2s"
    assert result.stage("detect_disks").status is StageStatus.SKIPPED
    assert {f.name for f in result.report.findings} == {"ip1"}
    assert "unattached disks collection timed out after 0.2s" in result.report.errors
    assert result.partial and result.exit_code == 3


def test_hung_cost_query_times_out_and_savings_become_unknown(tmp_path, hang):
    cost = FakeCost(total=10.0, hooks={"total": hang})
    graph = FakeGraph(disks=[disk_row("d1")])
    deps = make_deps(tmp_path, graph=graph, cost=cost, limits=fast_limits(cost_timeout_s=SHORT))
    result = run_workflow(deps)
    assert result.stage("collect_total_cost").status is StageStatus.TIMED_OUT
    # The two cost queries share a one-slot gate (Cost Management throttles per scope), so the
    # other one may also be starved while the hung call holds the gate: either outcome is valid,
    # and either way the report must say so.
    assert result.stage("collect_resource_costs").status in (
        StageStatus.OK,
        StageStatus.TIMED_OUT,
    )
    assert result.partial and any("timed out" in e for e in result.report.errors)
    assert result.report.findings[0].monthly_cost.amount is None


def test_one_hung_vm_metrics_call_only_loses_that_vm(tmp_path, hang):
    slow = rid("Microsoft.Compute/virtualMachines", "vm-slow")
    ok = rid("Microsoft.Compute/virtualMachines", "vm-ok")
    monitor = FakeMonitor({ok: (1.0, 5.0)}, hook=lambda r: hang() if r == slow else None)
    graph = FakeGraph(vms=[vm_row("vm-slow"), vm_row("vm-ok")])
    deps = make_deps(
        tmp_path, graph=graph, monitor=monitor, limits=fast_limits(metrics_call_timeout_s=SHORT)
    )
    result = run_workflow(deps)
    assert result.stage("collect_vms").status is StageStatus.OK
    assert {f.name for f in result.report.findings} == {"vm-ok"}
    assert any(
        slow in e and "metrics unavailable" in e and "timed out after 0.2s" in e
        for e in result.report.errors
    )
    assert result.partial


def test_a_late_result_after_the_timeout_cannot_change_the_report(tmp_path):
    release = threading.Event()
    finished = threading.Event()

    def slow_disks():
        release.wait(30)
        finished.set()

    graph = FakeGraph(disks=[disk_row("d1")], hooks={"disks": slow_disks})
    deps = make_deps(tmp_path, graph=graph, limits=fast_limits(collector_timeout_s=SHORT))
    result = run_workflow(deps)
    before = (tmp_path / "report.json").read_bytes()
    assert result.report.findings == []

    release.set()  # the abandoned call now completes and returns disk rows...
    assert finished.wait(5)
    time.sleep(0.1)
    assert (tmp_path / "report.json").read_bytes() == before  # ...which nobody ever sees
    assert result.report.findings == []


def test_hung_run_still_exits_the_process_cleanly():
    """A worker blocked forever must not keep the interpreter alive (daemon thread)."""
    import subprocess
    import sys
    import textwrap

    code = textwrap.dedent(
        """
        import threading
        from azure_finops_agent.workflow import call_with_timeout, StageTimeout
        try:
            call_with_timeout(lambda: threading.Event().wait(), 0.1)
        except StageTimeout:
            print("timed out")
        """
    )
    proc = subprocess.run(  # noqa: S603 - fixed argv, no user input
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=30, check=False
    )
    assert proc.returncode == 0 and proc.stdout.strip() == "timed out"
