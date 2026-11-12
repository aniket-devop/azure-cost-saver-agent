# ruff: noqa: E501  (the mutant table is data; long lines are intentional)
"""Mutation check for Phase 5: inject deliberate bugs, every one must be caught by the tests.

Usage (project root):  python scripts/mutation_check_workflow.py
Each mutant edits one source file in a temporary copy of the repo, runs the workflow tests, and
expects at least one failure. The real working tree is never modified.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
W = "src/azure_finops_agent/workflow/"

MUTANTS: list[tuple[str, str, str, str]] = [
    (
        "collectors made sequential",
        W + "graph.py",
        'graph.add_edge("start", name)  # fan out: collectors run in parallel',
        'graph.add_edge("start" if name == COLLECTORS[0] else COLLECTORS[COLLECTORS.index(name) - 1], name)',
    ),
    (
        "cost gate removed",
        W + "graph.py",
        "cost_gate = threading.Semaphore(1)",
        "cost_gate = threading.Semaphore(99)",
    ),
    (
        "worker bound ignored",
        W + "collect.py",
        "max_workers=min(deps.limits.max_workers, len(ids))",
        "max_workers=len(ids)",
    ),
    (
        "timeout never enforced",
        W + "timeouts.py",
        "if not done.wait(timeout_s):",
        "if not done.wait(timeout_s * 1000):",
    ),
    (
        "collector failure swallowed",
        W + "nodes.py",
        'StageStatus.FAILED, detail, t0, error=f"{label} failed: {detail}"',
        "StageStatus.FAILED, detail, t0",
    ),
    (
        "timeout not reported in report",
        W + "nodes.py",
        'StageStatus.TIMED_OUT, str(exc), t0, error=f"{label} {exc}"',
        "StageStatus.TIMED_OUT, str(exc), t0",
    ),
    (
        "detector runs on missing data",
        W + "detect.py",
        'if rows is None:\n            raise _missing("unattached disk", "Unattached disks")',
        'rows = rows or []\n        if False:\n            raise _missing("unattached disk", "Unattached disks")',
    ),
    (
        "budget ignored",
        W + "nodes.py",
        "> deps.limits.run_budget_s",
        "> deps.limits.run_budget_s * 1e9",
    ),
    ("LLM numbers not validated", W + "explain.py", "if unknown:", "if False:"),
    (
        "LLM figures recalculated check weakened",
        W + "explain.py",
        'numbers_in(_LIST_MARKER.sub("", cleaned)) - numbers_in(facts)',
        "set()",
    ),
    ("LLM given tools", W + "llm_azure_openai.py", "temperature=0,", "temperature=0, tools=[],"),
    (
        "notify failure aborts run",
        W + "nodes.py",
        "except Exception as exc:  # a stage must never abort the run",
        "except ZeroDivisionError as exc:",
    ),
    (
        "webhook url leaked",
        W + "notify.py",
        'raise NotificationError(f"Teams webhook failed ({type(exc).__name__})") from None',
        'raise NotificationError(f"Teams webhook failed ({exc})") from None',
    ),
    (
        "notification failure exit code lost",
        W + "graph.py",
        "if self.notification_failed:\n            return EXIT_NOTIFY_FAILED",
        "if False:\n            return EXIT_NOTIFY_FAILED",
    ),
    (
        "wall clock used instead of injected clock",
        W + "graph.py",
        '"started_at": deps.clock.now(),',
        '"started_at": __import__("datetime").datetime.now(__import__("datetime").UTC),',
    ),
    (
        "real sleep instead of injected sleep",
        W + "collect.py",
        "sleep=deps.clock.sleep,\n            )\n\n        result = call_with_timeout(call, deps.limits.collector_timeout_s, label=rows_key)",
        "sleep=None,\n            )\n\n        result = call_with_timeout(call, deps.limits.collector_timeout_s, label=rows_key)",
    ),
    (
        "legacy savings logic imported",
        W + "detect.py",
        "from ..collectors.errors import AzureDataError",
        "from ..collectors.errors import AzureDataError\nimport idle_finder  # noqa",
    ),
    (
        "explanation written into report",
        W + "graph.py",
        'write_text_atomic(deps.out_dir / EXPLANATION_FILE, explanation + "\\n")',
        'write_text_atomic(deps.out_dir / EXPLANATION_FILE, explanation + "\\n")\n    write_text_atomic(deps.out_dir / "report.md", explanation)',
    ),
    (
        "run summary exit code wrong",
        W + "graph.py",
        "if self.partial:\n            return EXIT_PARTIAL",
        "if self.partial:\n            return EXIT_OK",
    ),
]


def run_tests(repo: Path) -> bool:
    proc = subprocess.run(  # noqa: S603 - fixed argv
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-x",
            "tests/unit/workflow",
            "-p",
            "no:cacheprovider",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    return proc.returncode == 0


def main() -> int:
    survivors: list[str] = []
    killed = 0
    for name, rel, old, new in MUTANTS:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            shutil.copytree(
                ROOT,
                repo,
                ignore=shutil.ignore_patterns(
                    ".venv",
                    ".git",
                    "__pycache__",
                    ".mypy_cache",
                    ".ruff_cache",
                    ".pytest_cache",
                    "*.egg-info",
                ),
            )
            target = repo / rel
            text = target.read_text(encoding="utf-8")
            if old not in text:
                print(f"SKIPPED  {name}: pattern not found (script out of date)")
                survivors.append(name + " (pattern missing)")
                continue
            target.write_text(text.replace(old, new, 1), encoding="utf-8")
            env_ok = run_tests(repo)
            if env_ok:
                survivors.append(name)
                print(f"SURVIVED {name}")
            else:
                killed += 1
                print(f"killed   {name}")
    print(f"\n{killed}/{len(MUTANTS)} mutants killed")
    return 0 if not survivors else 1


if __name__ == "__main__":
    sys.exit(main())
