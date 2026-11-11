# ruff: noqa: E501
"""Hand-rolled mutation check for the reporting package (no extra dependencies).

Each mutant changes one line of a *temporary copy* of the project, runs the test-suite, and must
be killed (tests fail). A surviving mutant means a behaviour that no test protects.

Run from the repository root:  python scripts/mutation_check_reporting.py
"""

from __future__ import annotations

import os
import shutil
import subprocess  # noqa: S404
import sys
import tempfile
from pathlib import Path

R = "src/azure_finops_agent/reporting/"

# (description, file, old text, new text) - old text must occur exactly once.
MUTANTS: list[tuple[str, str, str, str]] = [
    (
        "potential findings counted as confirmed savings",
        R + "summary.py",
        "    confirmed = [f for f in report.findings if f.status is FindingStatus.CONFIRMED]",
        "    confirmed = list(report.findings)",
    ),
    (
        "unknown cost summed as zero",
        R + "summary.py",
        "        if c.amount is None or c.currency is None:\n            continue  # unknown is skipped, never treated as zero\n        total, n = sums.get(c.currency, (Decimal(0), 0))\n        sums[c.currency] = (total + c.amount, n + 1)",
        "        if c.currency is None:\n            continue\n        total, n = sums.get(c.currency, (Decimal(0), 0))\n        sums[c.currency] = (total + (c.amount or Decimal(0)), n + 1)",
    ),
    (
        "currencies merged into one bucket",
        R + "summary.py",
        "sums.get(c.currency, (Decimal(0), 0))",
        "sums.get('ANY', (Decimal(0), 0))",
    ),
    (
        "status always COMPLETE",
        R + "summary.py",
        "ReportStatus.PARTIAL if report.errors else ReportStatus.COMPLETE",
        "ReportStatus.COMPLETE",
    ),
    (
        "unknown-cost count includes potential findings",
        R + "summary.py",
        "for f in confirmed if not has_cost_figure(f)),\n        potential_without",
        "for f in report.findings if not has_cost_figure(f)),\n        potential_without",
    ),
    (
        "confirmed VM findings allowed",
        R + "invariants.py",
        "f.status is not FindingStatus.POTENTIAL",
        "f.status is FindingStatus.PARTIAL_NEVER",
    ),
    (
        "invariants not enforced in assemble",
        R + "assemble.py",
        "    check_invariants(report)\n    return report",
        "    return report",
    ),
    (
        "invariants not enforced when rendering JSON",
        R + "json_report.py",
        "def report_to_dict(report: Report) -> dict[str, Any]:\n    check_invariants(report)",
        "def report_to_dict(report: Report) -> dict[str, Any]:\n    pass",
    ),
    (
        "invariants not enforced when rendering Markdown",
        R + "markdown_report.py",
        "def render_markdown(report: Report) -> str:\n    check_invariants(report)",
        "def render_markdown(report: Report) -> str:\n    pass",
    ),
    (
        "potential sorted before confirmed",
        R + "common.py",
        "{FindingStatus.CONFIRMED: 0, FindingStatus.POTENTIAL: 1}",
        "{FindingStatus.CONFIRMED: 1, FindingStatus.POTENTIAL: 0}",
    ),
    (
        "resource-ID sort ignored",
        R + "common.py",
        "f.category, f.resource_id.lower(), f.resource_id, f.name)",
        "f.category, '', '', '')",
    ),
    ("JSON keys unsorted", R + "json_report.py", "sort_keys=True", "sort_keys=False"),
    (
        "JSON NaN allowed to leak",
        R + "json_report.py",
        "return value if math.isfinite(value) else None",
        "return value",
    ),
    (
        "JSON timestamps not normalised to UTC",
        R + "common.py",
        "value.astimezone(UTC).isoformat()",
        "value.isoformat()",
    ),
    (
        "decimal rendered in scientific notation",
        R + "common.py",
        'return format(value, "f")',
        "return str(value)",
    ),
    (
        "JSON parse skips derived-field check",
        R + "json_report.py",
        "        if expected[key] != value:",
        "        if False:",
    ),
    ("duplicates not dropped", R + "assemble.py", "        if key in seen:", "        if False:"),
    (
        "partial cost data limitation lost",
        R + "assemble.py",
        "    elif costs.partial:",
        "    elif False:",
    ),
    (
        "missing cost data limitation lost",
        R + "assemble.py",
        "    if costs is None:\n        limitations.append(NO_RESOURCE_COSTS)",
        "    if False:\n        limitations.append(NO_RESOURCE_COSTS)",
    ),
    ("errors not sorted", R + "assemble.py", "errors=sorted_unique(errors)", "errors=errors"),
    (
        "unknown confirmed cost shown as zero",
        R + "markdown_report.py",
        'return "Unknown (no cost data for this resource)"',
        'return "INR 0.00 per month (estimate)"',
    ),
    (
        "potential finding shown as confirmed estimate",
        R + "markdown_report.py",
        '        if f.status is FindingStatus.POTENTIAL:\n            return f"{money}',
        '        if False:\n            return f"{money}',
    ),
    (
        "estimate not labelled as estimate",
        R + "markdown_report.py",
        "per month (estimate; basis:",
        "per month (basis:",
    ),
    (
        "partial banner removed",
        R + "markdown_report.py",
        '    if errors:\n        out += [\n            "> **Partial report.**',
        '    if False:\n        out += [\n            "> **Partial report.**',
    ),
    (
        "pipe not escaped in table cells",
        R + "markdown_report.py",
        '        "|": "\\\\|",\n        "<"',
        '        "<"',
    ),
    ("html not escaped", R + "markdown_report.py", '        "<": "&lt;",\n', ""),
    (
        "newlines kept in cells",
        R + "markdown_report.py",
        'return _CONTROL.sub("", " ".join(str(value).split()))',
        "return str(value)",
    ),
    (
        "evidence unit dropped",
        R + "markdown_report.py",
        'return f"{shown} {e.unit}" if e.unit else shown',
        "return shown",
    ),
    (
        "evidence window dropped",
        R + "markdown_report.py",
        'return f"{start} to {end}"',
        'return "-"',
    ),
    (
        "thousands separator removed",
        R + "common.py",
        'return f"{currency} {amount:,.2f}"',
        'return f"{currency} {amount:.2f}"',
    ),
    (
        "empty-partial wording removed",
        R + "markdown_report.py",
        "this is not evidence that nothing is wasted",
        "nothing found",
    ),
    (
        "assumptions section removed",
        R + "markdown_report.py",
        '    out += ["## Assumptions", ""]',
        '    out += ["## Assumption", ""]',
    ),
    (
        "writer writes files before rendering both",
        R + "writer.py",
        "    markdown, json_text = render_markdown(report), render_json(report)\n    directory = Path(out_dir)\n    directory.mkdir(parents=True, exist_ok=True)",
        "    directory = Path(out_dir)\n    directory.mkdir(parents=True, exist_ok=True)\n    markdown, json_text = render_markdown(report), render_json(report)",
    ),
    (
        "temp file not cleaned up when replace fails",
        R + "writer.py",
        "        tmp.unlink(missing_ok=True)",
        "        pass",
    ),
    (
        "per-category counts swapped",
        R + "summary.py",
        "        row[f.status.value] += 1",
        "        row['confirmed'] += 1",
    ),
]


def run_tests(root: Path) -> bool:
    """True if the whole suite passes."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(root / "src")}
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    survivors: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "project"
        shutil.copytree(
            repo,
            work,
            ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".*_cache", "*.egg-info"),
        )
        if not run_tests(work):
            print("Baseline test run fails; fix the tests before mutation testing.")
            return 2
        for n, (name, rel, old, new) in enumerate(MUTANTS, start=1):
            path = work / rel
            original = path.read_text(encoding="utf-8")
            if original.count(old) != 1:
                print(f"[{n:02}] INVALID  {name}: pattern found {original.count(old)}x")
                return 2
            path.write_text(original.replace(old, new), encoding="utf-8", newline="\n")
            try:
                killed = not run_tests(work)
            finally:
                path.write_text(original, encoding="utf-8", newline="\n")
            print(f"[{n:02}] {'killed  ' if killed else 'SURVIVED'} {name}")
            if not killed:
                survivors.append(name)
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} mutants killed")
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
