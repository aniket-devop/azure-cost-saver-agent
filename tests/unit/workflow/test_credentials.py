import threading
import time

from azure.core.credentials import AccessToken

from azure_finops_agent.cli import Hooks, main
from azure_finops_agent.workflow import AzureClients, build_azure_clients
from azure_finops_agent.workflow.clients import CLI_PROCESS_TIMEOUT_S, CachingCredential

from .fakes import SUB, FakeCost, FakeGraph, FakeMonitor

SCOPE = "https://management.azure.com/.default"


class SlowCredential:
    """Stands in for a slow `az` call; counts how often it is really invoked."""

    def __init__(self, delay=0.0, lifetime=3600):
        self.calls = 0
        self.delay = delay
        self.lifetime = lifetime
        self.clock = [1000.0]

    def get_token(self, *scopes, **kwargs):
        self.calls += 1
        time.sleep(self.delay)
        return AccessToken(f"tok{self.calls}", int(self.clock[0] + self.lifetime))


def test_concurrent_callers_share_one_real_token_fetch():
    inner = SlowCredential(delay=0.1)
    cache = CachingCredential(inner, now=lambda: inner.clock[0])
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(cache.get_token(SCOPE))) for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert inner.calls == 1 and {r.token for r in results} == {"tok1"}


def test_token_is_refreshed_shortly_before_it_expires():
    inner = SlowCredential(lifetime=1000)
    cache = CachingCredential(inner, margin_s=300, now=lambda: inner.clock[0])
    assert cache.get_token(SCOPE)[0] == "tok1"
    inner.clock[0] += 600  # 400s left: still valid
    assert cache.get_token(SCOPE)[0] == "tok1"
    inner.clock[0] += 150  # 250s left: inside the 300s margin
    assert cache.get_token(SCOPE)[0] == "tok2"


def test_different_scopes_and_special_requests_are_not_mixed_up():
    inner = SlowCredential()
    cache = CachingCredential(inner, now=lambda: inner.clock[0])
    cache.get_token(SCOPE)
    cache.get_token("https://other/.default")
    assert inner.calls == 2
    cache.get_token(SCOPE, claims="x")
    cache.get_token(SCOPE, claims="x")
    assert inner.calls == 4  # claims requests always bypass the cache


def test_real_credential_is_built_with_a_long_cli_timeout_and_no_network(monkeypatch):
    seen = {}

    class FakeDefault:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def get_token(self, *scopes, **kwargs):
            raise AssertionError("constructing clients must not fetch a token")

    monkeypatch.setattr("azure.identity.DefaultAzureCredential", FakeDefault)
    clients = build_azure_clients(SUB)
    assert seen == {"process_timeout": CLI_PROCESS_TIMEOUT_S} and CLI_PROCESS_TIMEOUT_S >= 60
    assert clients.warm_up is not None


def hooks_with(warm_up):
    clients = AzureClients(
        graph=FakeGraph(), monitor=FakeMonitor(), cost=FakeCost(), warm_up=warm_up
    )
    return Hooks(clients=lambda _s: clients)


def test_failed_login_stops_immediately_with_a_clear_message(tmp_path, capsys):
    import io

    def bad():
        raise RuntimeError("secret detail")

    out, err = io.StringIO(), io.StringIO()
    code = main(
        ["run", "--out-dir", str(tmp_path)],
        env={"AZURE_SUBSCRIPTION_ID": SUB},
        hooks=hooks_with(bad),
        out=out,
        err=err,
    )
    assert code == 1 and "Azure login failed (RuntimeError)" in err.getvalue()
    assert "az login" in err.getvalue() and "secret detail" not in err.getvalue()
    assert not (tmp_path / "report.md").exists()  # no 300-second wait, no misleading report


def test_successful_warm_up_runs_once_before_the_workflow(tmp_path):
    import io

    calls = []
    code = main(
        ["run", "--out-dir", str(tmp_path)],
        env={"AZURE_SUBSCRIPTION_ID": SUB},
        hooks=hooks_with(lambda: calls.append(1)),
        out=io.StringIO(),
        err=io.StringIO(),
    )
    assert code == 0 and calls == [1]
