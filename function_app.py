"""DEPRECATED (Phase 5): legacy module kept temporarily; do not use in new code.

Superseded by the azure_finops_agent package (run: azure-finops run). The new LangGraph
workflow never imports this module. Known problems: hardcoded or guessed figures and no
partial-result handling. Scheduled for removal once the Azure Functions entry point is
migrated.
"""
import warnings

warnings.warn(
    "function_app.py is deprecated; use the azure_finops_agent package (azure-finops run)",
    DeprecationWarning,
    stacklevel=2,
)

import logging
import azure.functions as func
from cost_fetcher import get_last_7_days_cost
from idle_finder import find_idle_resources
from summarizer import summarize
from teams_sender import send_to_teams

app = func.FunctionApp()


# 9 AM IST = 03:30 UTC
@app.timer_trigger(schedule="0 30 3 * * *", arg_name="timer", run_on_startup=False)
def cost_agent(timer: func.TimerRequest) -> None:
    logging.info("Cost Agent Started")
    cost = get_last_7_days_cost()
    idle = find_idle_resources()
    summary = summarize(cost, idle)
    send_to_teams(summary)
    logging.info("Cost Agent Done")
