# Phase 4 - Deterministic Markdown + JSON reporting

Adds an LLM-free reporting engine that turns detector findings into `report.md` and
`report.json`. Identical inputs produce byte-identical files on Windows and Linux.
Existing Phase 1-3 files are **not modified**; this ZIP only adds files.

## What is in this ZIP

| Path | Purpose |
|---|---|
| `src/azure_finops_agent/reporting/` | The reporting package (assemble, summarize, render Markdown/JSON, write files) |
| `tests/unit/reporting/` | 60 new tests (unit, partial-failure, empty report, golden-file) + realistic fixture built with the real detectors |
| `tests/golden/report.md`, `report.json` | Golden files (compared byte-for-byte) |
| `docs/sample-report/report.md`, `report.json` | Published sample output (identical to the golden files; enforced by a test) |
| `scripts/mutation_check_reporting.py` | Mutation check: 35 deliberate bugs, every one must be caught by the tests |
| `.gitattributes` | Stops Git on Windows converting golden-file line endings to CRLF |

## Install (Windows PowerShell)

Run from the project root. Your existing files are kept; only new files are added.

```powershell
cd "C:\Users\aniket kumar\cost-agent"
git status -sb                      # should be clean on main
Expand-Archive -Path "$env:USERPROFILE\Downloads\phase4.zip" -DestinationPath . -Force
git status -sb                      # new files only, nothing modified
```

## Verify

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q                           # expect: 153 passed
ruff check .                        # expect: All checks passed!
ruff format --check .               # expect: 52 files already formatted
mypy                                # expect: Success: no issues found in 24 source files
python scripts\mutation_check_reporting.py    # expect: 35/35 mutants killed
```

## Use it

```python
from azure_finops_agent.reporting import assemble_report, write_reports

report = assemble_report(
    subscription_id=sub,
    generated_at=now,
    cost_summary=total_cost,
    results=[disk_result, ip_result, vm_result],
    costs=resource_costs,
)
write_reports(report, "out")  # writes out\report.md and out\report.json
```

`generated_at` is passed in (the reporter never reads the clock) so output is reproducible.

## Regenerate golden/sample files (only when you change the report on purpose)

```powershell
$env:UPDATE_GOLDEN = "1"; pytest tests\unit\reporting\test_golden.py -q; Remove-Item Env:UPDATE_GOLDEN
git diff tests/golden docs/sample-report    # review every change before committing
```

## Commit

```powershell
git add .
git commit -m "feat: add deterministic markdown and json reporting (phase 4)"
git push
```
