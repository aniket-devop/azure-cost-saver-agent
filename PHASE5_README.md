# Phase 5 - deterministic LangGraph workflow

Read-only. Nothing in this phase deploys to or modifies anything in Azure.

## What it does

```
start -> [collect: total cost | per-resource cost | disks | public IPs | VMs + CPU]  (parallel)
      -> collected -> [detect: disks | public IPs | VMs]                              (parallel)
      -> assemble (Phase 4) -> write_reports -> explain (optional) -> notify (optional) -> finalize
```

* Collectors are the Phase 2 functions, detectors the Phase 3 functions, report the Phase 4 code.
  The topology is fixed; no node (and no LLM) chooses the route.
* **Partial results are explicit.** A failed, timed-out or skipped stage becomes a report *error*
  (status `partial`), the dependent detector is skipped (never run on "no data"), and the report
  and `run_summary.json` still get written.
* **Timeouts**: each Azure call runs in a daemon worker thread with a hard limit; a hung call is
  abandoned and its late result is discarded. A run-time budget (injected clock) skips remaining
  stages explicitly once exceeded.
* **Parallelism**: Resource Graph queries and Cost Management run concurrently; the two Cost
  queries share a one-slot gate (Cost Management throttles per scope); Azure Monitor calls use a
  pool of `--max-workers` (default 8).
* **LLM (optional, `--explain`)**: receives one text block built from the finished report, no
  tools, no clients. Any explanation containing a number not present in that text is rejected.
  It is written to `explanation.txt`; `report.md` / `report.json` never depend on it.
* **Notification (optional, `--notify`)**: failure is recorded, never aborts the run, never
  alters the report, and never includes the webhook URL. No automatic retry (avoids duplicates).
* **Legacy modules** (`agent.py`, `cost_fetcher.py`, `idle_finder.py`, `mcp_server.py`,
  `summarizer.py`, `teams_sender.py`, `function_app.py`) are marked deprecated; the package never
  imports them (enforced by tests).

## Install (Windows PowerShell)

```powershell
cd path\to\azure-cost-saver-agent
py -3.11 -m venv .venv            # or: python -m venv .venv  (Python 3.11+)
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope Process Bypass
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Verify without Azure (offline demo)

One command runs everything (quality checks + all demo scenarios + reproducibility):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_phase5.ps1
```

Or manually:

```powershell
azure-finops demo                                   # healthy      -> exit 0
azure-finops demo --scenario partial                # disk query fails -> exit 3
azure-finops demo --scenario notify-failure         # webhook fails    -> exit 4
azure-finops demo --scenario llm-rejected           # LLM invents a number -> rejected, exit 0
azure-finops demo --explain                         # accepted explanation
$LASTEXITCODE                                       # exit code of the last command
Get-FileHash .\out-demo\report.json -Algorithm SHA256
```

Expected SHA-256 of the healthy demo `report.json`:
`A67A62D640A66832FC8E7DE8846D9833A49EA13144AA3D97E017E54D096B5FEB`

## Real run (read-only; needs Azure credentials with Reader + Cost Management Reader + Monitoring Reader)

```powershell
az login
$env:AZURE_SUBSCRIPTION_ID = "<subscription-guid>"
azure-finops run --out-dir out
# optional:
$env:TEAMS_WEBHOOK_URL = "https://..."; azure-finops run --notify
$env:AZURE_OPENAI_ENDPOINT = "https://..."; $env:AZURE_OPENAI_KEY = "..."
python -m pip install -e ".[llm]"; azure-finops run --explain
```

Options: `--collector-timeout S`, `--run-budget S`, `--max-workers N`, `-v`.
Output: `report.md`, `report.json`, `run_summary.json` (+ `explanation.txt` if accepted).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Complete report written |
| 1 | Fatal: configuration error, or no report written |
| 2 | Bad command-line usage |
| 3 | Report written but **partial** (see its Errors section) |
| 4 | Report complete, notification failed |
| 5 | Report partial and notification failed |

A rejected/failed `--explain` does not change the exit code (optional feature); it is shown in the
console output and `run_summary.json`.

## Maintenance

`python scripts/mutation_check_workflow.py` injects 19 deliberate bugs into a temporary copy and
checks that the workflow tests catch each one.
