import os
import json
from openai import AzureOpenAI


def summarize(cost: dict, idle: list) -> str:
    client = AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_KEY"],
        api_version="2024-06-01",
    )

    total_waste = sum(r["estimated_monthly_waste_inr"] for r in idle)

    prompt = (
        "Write a short plain-text summary (max 6 lines, no markdown) for an Azure cost report.\n"
        "Say: last 7 days total cost, what idle resources were found, and total monthly savings possible in INR.\n"
        "If no idle resources, say Azure usage looks clean.\n\n"
        f"Cost data: {json.dumps(cost)}\n"
        f"Idle resources: {json.dumps(idle)}\n"
        f"Total monthly waste INR: {total_waste}"
    )

    resp = client.chat.completions.create(
        model="gpt-mini",  # your deployment name
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()
