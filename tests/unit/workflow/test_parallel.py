"""Parallel execution is proven with barriers: they can only be passed if calls truly overlap."""

import random
import threading
import time

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

PROFILE = {rid("Microsoft.Compute/virtualMachines", "vm0"): (1.0, 5.0)}


def test_graph_queries_and_cost_query_run_at_the_same_time(tmp_path):
    barrier = threading.Barrier(4, timeout=5)  # 3 Resource Graph queries + 1 Cost query
    wait = barrier.wait
    graph = FakeGraph(
        disks=[disk_row("d1")],
        ips=[ip_row("ip1")],
        vms=[vm_row("vm0")],
        hooks={"disks": wait, "ips": wait, "vms": wait},
    )
    cost = FakeCost(hooks={"total": wait})
    result = run_workflow(make_deps(tmp_path, graph=graph, cost=cost))
    # Sequential execution would break the barrier and fail these collectors.
    for name in ("collect_disks", "collect_public_ips", "collect_vms", "collect_total_cost"):
        assert result.stage(name).status is StageStatus.OK, result.stage(name)
    assert graph.recorder.max_in_flight == 3
    assert not result.partial


def test_cost_management_queries_never_overlap(tmp_path):
    def slow():
        time.sleep(0.05)

    cost = FakeCost(hooks={"total": slow, "resource": slow})
    result = run_workflow(make_deps(tmp_path, cost=cost))
    assert sorted(cost.recorder.calls) == ["resource", "total"]
    assert cost.recorder.max_in_flight == 1  # one-slot gate: throttle-friendly
    assert result.exit_code == 0


def test_metrics_calls_run_concurrently_but_never_exceed_max_workers(tmp_path):
    barrier = threading.Barrier(4, timeout=5)
    monitor = FakeMonitor(hook=lambda _r: barrier.wait())
    graph = FakeGraph(vms=[vm_row(f"vm{i}") for i in range(12)])  # 12 = 3 full batches of 4
    deps = make_deps(tmp_path, graph=graph, monitor=monitor, limits=fast_limits(max_workers=4))
    result = run_workflow(deps)
    assert len(monitor.recorder.calls) == 12
    assert monitor.recorder.max_in_flight == 4  # reached 4 (barrier) and never more (bound)
    assert result.stage("collect_vms").detail.endswith("12/12")
    assert not result.partial


def test_max_workers_one_serialises_metrics_calls(tmp_path):
    monitor = FakeMonitor(hook=lambda _r: time.sleep(0.01))
    graph = FakeGraph(vms=[vm_row(f"vm{i}") for i in range(5)])
    run_workflow(
        make_deps(tmp_path, graph=graph, monitor=monitor, limits=fast_limits(max_workers=1))
    )
    assert monitor.recorder.max_in_flight == 1


def jittery_deps(tmp_path, seed):
    rng = random.Random(seed)  # noqa: S311 - test jitter, not security
    lock = threading.Lock()

    def jitter(*_args):
        with lock:
            delay = rng.random() * 0.01
        time.sleep(delay)

    graph = FakeGraph(
        disks=[disk_row(f"d{i}") for i in range(4)],
        ips=[ip_row(f"ip{i}") for i in range(3)],
        vms=[vm_row(f"vm{i}") for i in range(6)],
        hooks={"disks": jitter, "ips": jitter, "vms": jitter},
    )
    cost = FakeCost(
        per_resource={rid("Microsoft.Compute/disks", "d0"): 50.0},
        hooks={"total": jitter, "resource": jitter},
    )
    return make_deps(tmp_path, graph=graph, cost=cost, monitor=FakeMonitor(hook=jitter))


def test_output_is_byte_identical_whatever_order_threads_finish_in(tmp_path):
    outputs = set()
    for seed in range(8):
        out = tmp_path / f"run{seed}"
        run_workflow(jittery_deps(out, seed))
        outputs.add(((out / "report.json").read_bytes(), (out / "report.md").read_bytes()))
    assert len(outputs) == 1


def test_two_workflows_running_at_once_do_not_share_state(tmp_path):
    results = {}

    def run(label, n_disks):
        graph = FakeGraph(disks=[disk_row(f"{label}{i}") for i in range(n_disks)])
        cost = FakeCost(hooks={"total": lambda: time.sleep(0.05)})
        results[label] = run_workflow(make_deps(tmp_path / label, graph=graph, cost=cost))

    threads = [
        threading.Thread(target=run, args=("a", 1)),
        threading.Thread(target=run, args=("b", 3)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert {f.name for f in results["a"].report.findings} == {"a0"}
    assert {f.name for f in results["b"].report.findings} == {"b0", "b1", "b2"}
