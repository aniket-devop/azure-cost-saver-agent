import os
import requests


def send_to_teams(summary: str) -> None:
    url = os.environ["TEAMS_WEBHOOK_URL"]
    r = requests.post(url, json={"text": summary}, timeout=15)
    r.raise_for_status()
