"""The deterministic LangGraph workflow.

    start -> [5 collectors in parallel] -> collected -> [3 detectors in parallel]
          -> assemble -> write_reports -> explain (optional) -> notify (optional) -> finalize

The topology is fixed. No node decides what runs next, and no LLM is involved in control flow, in
Azure access, or in any figure. Collectors call Azure (Phase 2), detectors are pure (Phase 3), and
the report is built by Phase 4 code.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..models import Report
from ..reporting import ReportPaths, ReportStatus, ReportSummary, assemble_report, summarize
from ..reporting import write_reports as write_report_files
from ..reporting.common import format_timestamp
from . import collect, detect
from .deps import WorkflowDeps
from .explain import build_facts, validate_explanation
from .fsio import write_text_atomic
from .nodes import NodeResult, StageSkipped, guarded, over_budget
from .notify import build_notification_text
from .outcomes import StageOutcome, StageStatus, stage_sort_key
from .state import WorkflowState
from .timeouts import call_with_timeout

COLLECTORS = (
    "collect_total_cost",
    "collect_resource_costs",
    "collect_disks",
    "collect_public_ips",
    "collect_vms",
)
DETECTORS = ("detect_disks", "detect_public_ips", "detect_vms")
EXPLANATION_FILE = "explanation.txt"
RUN_SUMMARY_FILE = "run_summary.json"

EXIT_OK = 0
EXIT_FATAL = 1  # no report could be produced or written (argparse uses 2 for bad usage)
EXIT_PARTIAL = 3  # report written, but some data is missing (listed in the report)
EXIT_NOTIFY_FAILED = 4  # report complete, notification failed
EXIT_PARTIAL_AND_NOTIFY_FAILED = 5


# ---- result ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunResult:
    report: Report | None
    summary: ReportSummary | None
    paths: ReportPaths | None
    stages: tuple[StageOutcome, ...]
    explanation: str | None

    def stage(self, name: str) -> StageOutcome | None:
        return next((s for s in self.stages if s.name == name), None)

    @property
    def partial(self) -> bool:
        return self.summary is not None and self.summary.status is ReportStatus.PARTIAL

    @property
    def notification_failed(self) -> bool:
        s = self.stage("notify")
        return s is not None and s.status in (StageStatus.FAILED, StageStatus.TIMED_OUT)

    @property
    def exit_code(self) -> int:
        if self.report is None or self.paths is None:
            return EXIT_FATAL
        if self.partial and self.notification_failed:
            return EXIT_PARTIAL_AND_NOTIFY_FAILED
        if self.partial:
            return EXIT_PARTIAL
        if self.notification_failed:
            return EXIT_NOTIFY_FAILED
        return EXIT_OK


def build_result(state: WorkflowState) -> RunResult:
    report = state.get("report")
    return RunResult(
        report=report,
        summary=summarize(report) if report is not None else None,
        paths=state.get("report_paths"),
        stages=tuple(sorted(state.get("stages", []), key=stage_sort_key)),
        explanation=state.get("explanation"),
    )


def run_summary_text(result: RunResult, state: WorkflowState) -> str:
    started = state.get("started_at")
    data: dict[str, Any] = {
        "schema_version": "1.0",
        "started_at": format_timestamp(started) if started is not None else None,
        "report_status": result.summary.status.value if result.summary else "unavailable",
        "exit_code": result.exit_code,
        "explanation_included": result.explanation is not None,
        "stages": [
            {
                "name": s.name,
                "status": s.status.value,
                "detail": s.detail,
                "duration_seconds": round(s.duration_s, 3),
            }
            for s in result.stages
        ],
    }
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


# ---- nodes that are not collectors/detectors -----------------------------------------------


def _start(deps: WorkflowDeps) -> Mapping[str, Any]:
    return {
        "started_at": deps.clock.now(),
        "started_monotonic": deps.clock.monotonic(),
    }


def _assemble(deps: WorkflowDeps, state: WorkflowState) -> NodeResult:
    results = [
        r
        for r in (state.get("disk_result"), state.get("ip_result"), state.get("vm_result"))
        if r is not None
    ]
    report = assemble_report(
        subscription_id=deps.settings.subscription_id,
        generated_at=state["started_at"],
        cost_summary=state.get("total_cost"),
        results=results,
        costs=state.get("resource_costs"),
        extra_errors=state.get("errors", []),
        extra_limitations=state.get("limitations", []),
    )
    return NodeResult({"report": report}, f"{len(report.findings)} findings")


def _write(deps: WorkflowDeps, state: WorkflowState) -> NodeResult:
    report = state.get("report")
    if report is None:
        raise StageSkipped("no report was assembled")
    paths = write_report_files(report, deps.out_dir)
    return NodeResult({"report_paths": paths}, f"{paths.markdown.name}, {paths.json.name}")


def _explain(deps: WorkflowDeps, state: WorkflowState) -> NodeResult:
    explainer = deps.explainer
    report = state.get("report")
    if explainer is None:
        raise StageSkipped("not requested")
    if report is None:
        raise StageSkipped("no report to explain")
    if over_budget(deps, state):
        raise StageSkipped("run time budget exceeded")
    facts = build_facts(report)
    raw = call_with_timeout(
        lambda: explainer.explain(facts), deps.limits.explain_timeout_s, label="explain"
    )
    explanation = validate_explanation(raw, facts)  # raises ExplanationRejected
    write_text_atomic(deps.out_dir / EXPLANATION_FILE, explanation + "\n")
    return NodeResult({"explanation": explanation}, EXPLANATION_FILE)


def _notify(deps: WorkflowDeps, state: WorkflowState) -> NodeResult:
    notifier = deps.notifier
    report = state.get("report")
    if notifier is None:
        raise StageSkipped("not requested")
    if report is None:
        raise StageSkipped("no report to send")
    message = build_notification_text(report, state.get("explanation"))
    call_with_timeout(lambda: notifier.send(message), deps.limits.notify_timeout_s, label="notify")
    return NodeResult({}, "sent")


def _finalize(deps: WorkflowDeps, state: WorkflowState) -> NodeResult:
    result = build_result(state)
    deps.out_dir.mkdir(parents=True, exist_ok=True)
    write_text_atomic(deps.out_dir / RUN_SUMMARY_FILE, run_summary_text(result, state))
    return NodeResult({}, RUN_SUMMARY_FILE)


# ---- graph ----------------------------------------------------------------------------------


def build_workflow(deps: WorkflowDeps) -> CompiledStateGraph[Any, Any, Any, Any]:
    cost_gate = threading.Semaphore(1)  # Cost Management: one query at a time per run

    def start(state: WorkflowState) -> dict[str, Any]:
        return dict(_start(deps))

    nodes: dict[str, Any] = {
        "start": start,
        "collect_total_cost": guarded(
            "collect_total_cost",
            "total cost collection",
            deps,
            collect.collect_total_cost(deps, cost_gate),
        ),
        "collect_resource_costs": guarded(
            "collect_resource_costs",
            "per-resource cost collection",
            deps,
            collect.collect_resource_costs(deps, cost_gate),
        ),
        "collect_disks": guarded(
            "collect_disks", "unattached disks collection", deps, collect.collect_disks(deps)
        ),
        "collect_public_ips": guarded(
            "collect_public_ips",
            "unattached public IPs collection",
            deps,
            collect.collect_public_ips(deps),
        ),
        "collect_vms": guarded(
            "collect_vms", "virtual machines collection", deps, collect.collect_vms(deps)
        ),
        "collected": lambda state: {},
        "detect_disks": guarded(
            "detect_disks", "unattached disks detection", deps, detect.detect_disks(deps)
        ),
        "detect_public_ips": guarded(
            "detect_public_ips",
            "unattached public IPs detection",
            deps,
            detect.detect_public_ips(deps),
        ),
        "detect_vms": guarded(
            "detect_vms", "under-utilized VMs detection", deps, detect.detect_vms(deps)
        ),
        "assemble": guarded(
            "assemble", "report assembly", deps, lambda s: _assemble(deps, s), always_run=True
        ),
        "write_reports": guarded(
            "write_reports",
            "report writing",
            deps,
            lambda s: _write(deps, s),
            always_run=True,
            affects_report=False,
        ),
        "explain": guarded(
            "explain",
            "explanation",
            deps,
            lambda s: _explain(deps, s),
            always_run=True,
            affects_report=False,
        ),
        "notify": guarded(
            "notify",
            "notification",
            deps,
            lambda s: _notify(deps, s),
            always_run=True,
            affects_report=False,
        ),
        "finalize": guarded(
            "finalize",
            "run summary",
            deps,
            lambda s: _finalize(deps, s),
            always_run=True,
            affects_report=False,
        ),
    }

    graph: StateGraph[WorkflowState, None, WorkflowState, WorkflowState] = StateGraph(WorkflowState)
    for name, fn in nodes.items():
        graph.add_node(name, fn)

    graph.add_edge(START, "start")
    for name in COLLECTORS:
        graph.add_edge("start", name)  # fan out: collectors run in parallel
    graph.add_edge(list(COLLECTORS), "collected")  # barrier: wait for every collector
    for name in DETECTORS:
        graph.add_edge("collected", name)  # fan out: detectors run in parallel
    graph.add_edge(list(DETECTORS), "assemble")  # barrier: wait for every detector
    graph.add_edge("assemble", "write_reports")
    graph.add_edge("write_reports", "explain")
    graph.add_edge("explain", "notify")
    graph.add_edge("notify", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def run_workflow(deps: WorkflowDeps) -> RunResult:
    app = build_workflow(deps)
    final = app.invoke(
        {"stages": [], "errors": [], "limitations": []},
        config={"max_concurrency": len(COLLECTORS)},
    )
    return build_result(cast(WorkflowState, final))
