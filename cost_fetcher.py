import os
import time
from azure.core.exceptions import HttpResponseError
from datetime import datetime, timedelta, timezone
from azure.identity import DefaultAzureCredential
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.costmanagement.models import (
    QueryDefinition, QueryTimePeriod, QueryDataset, QueryAggregation
)


def get_last_7_days_cost() -> dict:
    subscription_id = os.environ["AZURE_SUBSCRIPTION_ID"]
    scope = f"/subscriptions/{subscription_id}"

    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=7)

    client = CostManagementClient(DefaultAzureCredential())

    query = QueryDefinition(
        type="ActualCost",
        timeframe="Custom",
        time_period=QueryTimePeriod(from_property=start, to=end),
        dataset=QueryDataset(
            granularity="None",
            aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
        ),
    )

    result = None
    for attempt in range(4):
        try:
            result = client.query.usage(scope=scope, parameters=query)
            break
        except HttpResponseError as e:
            if e.status_code != 429 or attempt == 3:
                raise
            time.sleep(15 * (attempt + 1))

    total_cost = 0.0
    currency = "INR"
    if result.rows:
        columns = [c.name for c in result.columns]
        row = result.rows[0]
        total_cost = float(row[columns.index("Cost")])
        if "Currency" in columns:
            currency = row[columns.index("Currency")]

    return {
        "total_cost": round(total_cost, 2),
        "currency": currency,
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
    }

