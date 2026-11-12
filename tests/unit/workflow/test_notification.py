"""A failed notification never changes the report and never aborts the run."""

import io
import json
import threading
import urllib.error

import pytest
from pydantic import SecretStr

from azure_finops_agent.workflow import (
    NotificationError,
    StageStatus,
    TeamsWebhookNotifier,
    build_notification_text,
    run_workflow,
)
from azure_finops_agent.workflow import notify as notify_mod

from .fakes import (
    FakeCost,
    FakeGraph,
    RecordingNotifier,
    disk_row,
    fast_limits,
    make_deps,
    rid,
)

URL = "https://example.invalid/webhook/SECRET-TOKEN-123"


def deps_with(tmp_path, notifier, **kw):
    graph = kw.pop("graph", FakeGraph(disks=[disk_row("d1")]))
    cost = FakeCost(per_resource={rid("Microsoft.Compute/disks", "d1"): 200.0})
    return make_deps(tmp_path, graph=graph, cost=cost, notifier=notifier, **kw)


def test_successful_notification_contains_report_figures(tmp_path):
    notifier = RecordingNotifier()
    result = run_workflow(deps_with(tmp_path, notifier))
    assert result.stage("notify").status is StageStatus.OK and result.exit_code == 0
    (message,) = notifier.messages
    assert "Status: COMPLETE" in message and "INR 200.00" in message
    assert message == build_notification_text(result.report)


def test_notification_is_not_sent_unless_a_notifier_is_injected(tmp_path):
    result = run_workflow(deps_with(tmp_path, None))
    assert result.stage("notify").status is StageStatus.SKIPPED
    assert result.stage("notify").detail == "not requested" and result.exit_code == 0


def test_notification_failure_is_recorded_and_report_is_unaffected(tmp_path):
    def fail():
        raise NotificationError("Teams webhook returned HTTP 500")

    ok_dir, bad_dir = tmp_path / "ok", tmp_path / "bad"
    run_workflow(deps_with(ok_dir, None))
    result = run_workflow(deps_with(bad_dir, RecordingNotifier(hook=fail)))
    stage = result.stage("notify")
    assert stage.status is StageStatus.FAILED and "HTTP 500" in stage.detail
    assert result.exit_code == 4 and not result.partial  # report is complete; delivery failed
    for name in ("report.json", "report.md"):  # byte-identical to a run with no notifier
        assert (bad_dir / name).read_bytes() == (ok_dir / name).read_bytes()
    assert result.stage("finalize").status is StageStatus.OK  # the run carried on


def test_unexpected_notifier_errors_do_not_leak_their_message(tmp_path):
    def leak():
        raise RuntimeError(f"cannot reach {URL}")

    result = run_workflow(deps_with(tmp_path, RecordingNotifier(hook=leak)))
    assert result.stage("notify").detail == "RuntimeError"
    for path in tmp_path.iterdir():
        assert "SECRET-TOKEN-123" not in path.read_text(encoding="utf-8")


def test_hung_notification_times_out(tmp_path):
    release = threading.Event()
    try:
        notifier = RecordingNotifier(hook=lambda: release.wait(30))
        deps = deps_with(tmp_path, notifier, limits=fast_limits(notify_timeout_s=0.2))
        result = run_workflow(deps)
        assert result.stage("notify").status is StageStatus.TIMED_OUT
        assert result.exit_code == 4
        assert (tmp_path / "report.md").exists()
    finally:
        release.set()


def test_partial_report_and_failed_notification_have_their_own_exit_code(tmp_path):
    def fail():
        raise NotificationError("down")

    def outage():
        raise OSError("graph outage")

    graph = FakeGraph(hooks={"disks": outage})
    result = run_workflow(deps_with(tmp_path, RecordingNotifier(hook=fail), graph=graph))
    assert result.partial and result.notification_failed and result.exit_code == 5


def test_partial_report_notification_warns_the_reader(tmp_path):
    def outage():
        raise OSError("graph outage")

    notifier = RecordingNotifier()
    run_workflow(deps_with(tmp_path, notifier, graph=FakeGraph(hooks={"disks": outage})))
    assert "Status: PARTIAL" in notifier.messages[0]
    assert "WARNING: partial report" in notifier.messages[0]


# ---- TeamsWebhookNotifier ---------------------------------------------------------------------


def posting(status=200, raises=None):
    calls = []

    def post(url, body, timeout):
        calls.append((url, body, timeout))
        if raises is not None:
            raise raises
        return status

    return post, calls


def test_teams_notifier_posts_the_legacy_text_payload():
    post, calls = posting()
    TeamsWebhookNotifier(SecretStr(URL), timeout_s=7, post=post).send("hello")
    ((url, body, timeout),) = calls
    assert url == URL and json.loads(body) == {"text": "hello"} and timeout == 7


def test_teams_notifier_requires_https():
    with pytest.raises(NotificationError, match="https"):
        TeamsWebhookNotifier(SecretStr("http://example.invalid/x"))
    assert "SECRET" not in repr(SecretStr(URL))


@pytest.mark.parametrize("status", [199, 301, 400, 429, 500])
def test_teams_notifier_rejects_non_2xx(status):
    post, _ = posting(status=status)
    with pytest.raises(NotificationError, match=f"HTTP {status}"):
        TeamsWebhookNotifier(SecretStr(URL), post=post).send("x")


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError(URL, 503, "Service Unavailable", {}, io.BytesIO()),
        urllib.error.URLError(ConnectionResetError(f"reset talking to {URL}")),
        RuntimeError(f"boom {URL}"),
    ],
)
def test_teams_notifier_errors_never_contain_the_webhook_url(error):
    post, _ = posting(raises=error)
    with pytest.raises(NotificationError) as info:
        TeamsWebhookNotifier(SecretStr(URL), post=post).send("x")
    assert "SECRET-TOKEN-123" not in str(info.value) and "example.invalid" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_default_transport_maps_http_errors_without_touching_the_network(monkeypatch):
    def fake_urlopen(request, timeout):
        assert request.full_url == URL and request.get_method() == "POST" and timeout == 15
        raise urllib.error.HTTPError(URL, 410, "Gone", {}, io.BytesIO())

    monkeypatch.setattr(notify_mod.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(NotificationError, match="HTTP 410"):
        TeamsWebhookNotifier(SecretStr(URL)).send("x")


def test_default_transport_success_path(monkeypatch):
    class Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(notify_mod.urllib.request, "urlopen", lambda request, timeout: Response())
    TeamsWebhookNotifier(SecretStr(URL)).send("x")  # no exception
