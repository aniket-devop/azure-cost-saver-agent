from datetime import UTC, datetime
from decimal import Decimal

import pytest

from azure_finops_agent.collectors.costs import ResourceCosts
from azure_finops_agent.detectors import DetectionContext

SUB = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def rid(kind, name):
    return f"/subscriptions/{SUB}/resourceGroups/rg1/providers/{kind}/{name}"


def costs(**amounts):
    return ResourceCosts(
        amounts={k.lower(): Decimal(str(v)) for k, v in amounts.items()},
        currency="INR",
        days=30,
        start_date="2026-10-12",
        end_date="2026-11-11",
        partial=False,
    )


@pytest.fixture
def ctx():
    return DetectionContext(subscription_id=SUB, now=NOW)
