"""DEPRECATED (Phase 5): legacy module kept temporarily; do not use in new code.

Superseded by the azure_finops_agent package (run: azure-finops run). The new LangGraph
workflow never imports this module. Known problems: hardcoded or guessed figures and no
partial-result handling. Scheduled for removal once the Azure Functions entry point is
migrated.
"""
import warnings

warnings.warn(
    "teams_sender.py is deprecated; use the azure_finops_agent package (azure-finops run)",
    DeprecationWarning,
    stacklevel=2,
)

import os
import requests


def send_to_teams(summary: str) -> None:
    url = os.environ["TEAMS_WEBHOOK_URL"]
    r = requests.post(url, json={"text": summary}, timeout=15)
    r.raise_for_status()
