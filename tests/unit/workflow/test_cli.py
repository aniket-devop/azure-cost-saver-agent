import io
import json

import pytest

from azure_finops_agent import cli
from azure_finops_agent.cli import Hooks, main
from azure_finops_agent.workflow import ManualClock, NotificationError

from .fakes import (
    SUB,
    FakeCost,
    FakeGraph,
    FakeMonitor,
    RecordingNotifier,
    StaticExplainer,
    disk_row,
)


def run_cli(argv, **kw):
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, out=out, err=err, **kw)
    return code, out.getvalue(), err.getvalue()


def fake_hooks(**kw):
    graph = kw.pop("graph", FakeGraph(disks=[disk_row("d1")]))
    from azure_finops_agent.workflow import AzureClients

    clients = AzureClients(graph=graph, monitor=FakeMonitor(), cost=FakeCost())
    return Hooks(clients=lambda _s: clients, clock=ManualClock(), **kw)


@pytest.mark.parametrize(
    ("scenario", "code"),
    [("healthy", 0), ("partial", 3), ("notify-failure", 4), ("llm-rejected", 0)],
)
def test_demo_scenarios_have_the_documented_exit_codes(tmp_path, scenario, code):
    rc, out, _ = run_cli(["demo", "--scenario", scenario, "--out-dir", str(tmp_path)])
    assert rc == code and f"Exit code: {code}" in out
    assert "DEMO MODE" in out and "no Azure or network calls" in out
    summary = json.loads((tmp_path / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["exit_code"] == code


def test_demo_output_is_ascii_and_reproducible(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _, out_a, _ = run_cli(["demo", "--out-dir", str(a), "--explain"])
    run_cli(["demo", "--out-dir", str(b), "--explain"])
    out_a.encode("ascii")
    for name in ("report.md", "report.json", "explanation.txt"):
        assert (a / name).read_bytes() == (b / name).read_bytes()


def test_demo_partial_scenario_says_what_is_missing(tmp_path):
    _, out, _ = run_cli(["demo", "--scenario", "partial", "--out-dir", str(tmp_path)])
    assert "Status: PARTIAL" in out and "unattached disks collection failed" in out


def test_demo_rejects_explain_for_partial(tmp_path):
    rc, _, err = run_cli(["demo", "--scenario", "partial", "--explain", "--out-dir", str(tmp_path)])
    assert rc == 1 and "not available" in err


def test_run_requires_a_subscription_id(tmp_path):
    rc, _, err = run_cli(["run", "--out-dir", str(tmp_path)], env={})
    assert rc == 1 and "AZURE_SUBSCRIPTION_ID is required" in err


def test_run_uses_injected_clients_and_writes_reports(tmp_path):
    env = {"AZURE_SUBSCRIPTION_ID": SUB}
    rc, out, _ = run_cli(["run", "--out-dir", str(tmp_path)], env=env, hooks=fake_hooks())
    assert rc == 0 and f"Analysing subscription {SUB}" in out
    assert (tmp_path / "report.md").exists()


def test_run_notify_needs_a_webhook_unless_injected(tmp_path):
    env = {"AZURE_SUBSCRIPTION_ID": SUB}
    rc, _, err = run_cli(
        ["run", "--notify", "--out-dir", str(tmp_path)], env=env, hooks=fake_hooks()
    )
    assert rc == 1 and "TEAMS_WEBHOOK_URL" in err


def test_run_notification_failure_maps_to_exit_code_4(tmp_path):
    def fail():
        raise NotificationError("HTTP 500")

    env = {"AZURE_SUBSCRIPTION_ID": SUB}
    hooks = fake_hooks(notifier=lambda _s: RecordingNotifier(hook=fail))
    rc, out, _ = run_cli(["run", "--notify", "--out-dir", str(tmp_path)], env=env, hooks=hooks)
    assert rc == 4 and "Notification: failed" in out and (tmp_path / "report.json").exists()


def test_run_explain_uses_injected_explainer_and_rejects_bad_output(tmp_path):
    env = {"AZURE_SUBSCRIPTION_ID": SUB}
    hooks = fake_hooks(explainer=lambda _e: StaticExplainer("Save INR 777.00."))
    rc, out, _ = run_cli(["run", "--explain", "--out-dir", str(tmp_path)], env=env, hooks=hooks)
    assert rc == 0 and "Explanation: failed" in out
    assert not (tmp_path / "explanation.txt").exists()


def test_run_explain_without_openai_settings_fails_fast(tmp_path):
    env = {"AZURE_SUBSCRIPTION_ID": SUB}
    rc, _, err = run_cli(
        ["run", "--explain", "--out-dir", str(tmp_path)], env=env, hooks=fake_hooks()
    )
    assert rc == 1 and "AZURE_OPENAI_ENDPOINT" in err


def test_run_options_override_limits_and_are_validated(tmp_path):
    env = {"AZURE_SUBSCRIPTION_ID": SUB}
    rc, _, err = run_cli(
        ["run", "--max-workers", "0", "--out-dir", str(tmp_path)], env=env, hooks=fake_hooks()
    )
    assert rc == 1 and "max_workers" in err
    rc, _, _ = run_cli(
        ["run", "--run-budget", "5", "--max-workers", "2", "--out-dir", str(tmp_path)],
        env=env,
        hooks=fake_hooks(),
    )
    assert rc == 0


def test_usage_errors_exit_with_2():
    with pytest.raises(SystemExit) as info:
        run_cli([])
    assert info.value.code == 2
    with pytest.raises(SystemExit) as info:
        run_cli(["demo", "--scenario", "nope"])
    assert info.value.code == 2


def test_unexpected_errors_print_only_the_type_name(tmp_path, monkeypatch):
    def explode(_deps):
        raise RuntimeError("secret-value")

    monkeypatch.setattr(cli, "run_workflow", explode)
    rc, out, err = run_cli(["demo", "--out-dir", str(tmp_path)])
    assert rc == 1 and "RuntimeError" in err and "secret-value" not in out + err


def test_real_client_construction_makes_no_network_call():
    from azure_finops_agent.workflow import build_azure_clients

    class Cred:
        def get_token(self, *scopes, **kwargs):
            raise AssertionError("constructing clients must not fetch a token")

    clients = build_azure_clients(SUB, credential=Cred())  # type: ignore[arg-type]
    assert hasattr(clients.graph, "resources") and hasattr(clients.monitor, "metrics")
    assert hasattr(clients.cost, "query")


def test_the_network_guard_is_active():
    import socket

    with pytest.raises(AssertionError, match="test tried to"):
        socket.create_connection(("203.0.113.1", 80), timeout=1)
