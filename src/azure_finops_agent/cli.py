"""Command line: ``azure-finops run`` (real Azure, read-only) and ``azure-finops demo`` (offline).

Exit codes: 0 ok | 1 fatal (no report written) | 2 bad usage | 3 partial report |
4 notification failed | 5 partial report and notification failed.

All output is plain ASCII so it is safe in Windows PowerShell regardless of console code page.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TextIO

from . import __version__
from .config import ConfigError, Settings, load_settings
from .workflow import (
    AzureClients,
    Clock,
    Explainer,
    LlmExplainer,
    NotificationError,
    Notifier,
    RunLimits,
    RunResult,
    SystemClock,
    TeamsWebhookNotifier,
    WorkflowDeps,
    build_azure_clients,
    run_workflow,
)
from .workflow import demo as demo_mod
from .workflow.llm_azure_openai import completer_from_env


@dataclass(frozen=True)
class Hooks:
    """Injection points so tests never reach Azure, the LLM or Teams (None in production)."""

    clients: Callable[[Settings], AzureClients] | None = None
    clock: Clock | None = None
    explainer: Callable[[Mapping[str, str]], Explainer] | None = None
    notifier: Callable[[Settings], Notifier] | None = None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="azure-finops",
        description="Read-only Azure cost-saving analysis (deterministic LangGraph workflow).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="analyse the subscription in AZURE_SUBSCRIPTION_ID")
    run.add_argument("--out-dir", default="out", help="where reports are written (default: out)")
    run.add_argument("--explain", action="store_true", help="add an LLM explanation (optional)")
    run.add_argument("--notify", action="store_true", help="post a summary to Teams")
    run.add_argument("--collector-timeout", type=float, metavar="SECONDS")
    run.add_argument("--run-budget", type=float, metavar="SECONDS")
    run.add_argument("--max-workers", type=int, metavar="N")
    run.add_argument("-v", "--verbose", action="store_true")

    demo = sub.add_parser("demo", help="run the workflow on synthetic data (no Azure, no network)")
    demo.add_argument("--scenario", choices=demo_mod.SCENARIOS, default="healthy")
    demo.add_argument("--out-dir", default="out-demo")
    demo.add_argument("--explain", action="store_true", help="add the simulated explanation")
    demo.add_argument("-v", "--verbose", action="store_true")
    return parser


def _limits(args: argparse.Namespace) -> RunLimits:
    limits = RunLimits()
    if args.collector_timeout is not None:
        limits = replace(limits, collector_timeout_s=args.collector_timeout)
    if args.run_budget is not None:
        limits = replace(limits, run_budget_s=args.run_budget)
    if args.max_workers is not None:
        limits = replace(limits, max_workers=args.max_workers)
    return RunLimits(**limits.__dict__)  # re-validate


def _print_result(result: RunResult, emit: Callable[[str], None]) -> None:
    status = result.summary.status.value.upper() if result.summary else "NO REPORT"
    emit(f"Status: {status}")
    if result.summary is not None:
        s = result.summary
        emit(
            f"Findings: {s.total_findings} ({s.confirmed_findings} confirmed, "
            f"{s.potential_findings} potential)"
        )
    if result.paths is not None:
        emit(f"Report:   {result.paths.markdown}")
        emit(f"JSON:     {result.paths.json}")
    emit("Stages:")
    for st in result.stages:
        detail = f" - {st.detail}" if st.detail else ""
        emit(f"  {st.status.value:<10} {st.name}{detail}")
    if result.report is not None and result.report.errors:
        emit("Report errors (data is missing):")
        for e in sorted(set(result.report.errors)):
            emit(f"  - {e}")
    explain = result.stage("explain")
    if explain is not None and explain.status.value != "skipped":
        emit(f"Explanation: {explain.status.value} - {explain.detail}")
    notify = result.stage("notify")
    if notify is not None and notify.status.value != "skipped":
        emit(f"Notification: {notify.status.value} - {notify.detail}")
    emit(f"Exit code: {result.exit_code}")


def _run_real(
    args: argparse.Namespace,
    env: Mapping[str, str],
    hooks: Hooks,
    emit: Callable[[str], None],
) -> int:
    settings = load_settings(env)
    clients = (hooks.clients or (lambda s: build_azure_clients(s.subscription_id)))(settings)

    explainer: Explainer | None = None
    if args.explain:
        explainer = (
            hooks.explainer(env)
            if hooks.explainer is not None
            else LlmExplainer(completer_from_env(env))
        )
    notifier: Notifier | None = None
    if args.notify:
        if hooks.notifier is not None:
            notifier = hooks.notifier(settings)
        elif settings.teams_webhook_url is None:
            raise ConfigError("--notify requires TEAMS_WEBHOOK_URL")
        else:
            notifier = TeamsWebhookNotifier(settings.teams_webhook_url)

    deps = WorkflowDeps(
        settings=settings,
        clients=clients,
        clock=hooks.clock or SystemClock(),
        out_dir=Path(args.out_dir),
        limits=_limits(args),
        explainer=explainer,
        notifier=notifier,
    )
    emit(f"Analysing subscription {settings.subscription_id} (read-only)")
    result = run_workflow(deps)
    _print_result(result, emit)
    return result.exit_code


def _run_demo(args: argparse.Namespace, emit: Callable[[str], None]) -> int:
    scenario: str = args.scenario
    if args.explain and scenario == "partial":
        raise ConfigError("--explain is not available for the 'partial' scenario")
    notifier = demo_mod.DemoNotifier(fail=scenario == "notify-failure")
    deps = WorkflowDeps(
        settings=demo_mod.demo_settings(),
        clients=demo_mod.build_demo_clients(scenario),
        clock=demo_mod.demo_clock(),
        out_dir=Path(args.out_dir),
        explainer=demo_mod.demo_explainer(scenario, args.explain),
        notifier=notifier,
    )
    emit(f"DEMO MODE ({scenario}): synthetic data, no Azure or network calls")
    result = run_workflow(deps)
    _print_result(result, emit)
    if notifier.sent is not None:
        emit("Simulated notification text (not sent anywhere):")
        for line in notifier.sent.splitlines():
            emit(f"  | {line}")
    return result.exit_code


def _configure_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")  # never crash on a legacy console code page


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    hooks: Hooks | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    if out is None and err is None:
        _configure_streams()
    stdout = out if out is not None else sys.stdout
    stderr = err if err is not None else sys.stderr

    def emit(line: str) -> None:
        print(line, file=stdout)

    def fail(line: str) -> None:
        print(line, file=stderr)

    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if getattr(args, "verbose", False) else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=stderr,
    )
    environment: Mapping[str, str] = os.environ if env is None else env
    try:
        if args.command == "demo":
            return _run_demo(args, emit)
        return _run_real(args, environment, hooks or Hooks(), emit)
    except (ConfigError, NotificationError, ValueError) as exc:
        fail(f"error: {exc}")
        return 1
    except Exception as exc:
        fail(f"error: unexpected failure ({type(exc).__name__})")
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
