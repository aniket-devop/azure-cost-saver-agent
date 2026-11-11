"""Typed data contracts shared by detectors, reports, MCP tools and the agent.

Every finding must be traceable to Azure data: resource ID, evidence and timestamp.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FindingStatus(StrEnum):
    """CONFIRMED: state verified directly (e.g. disk has no owner).
    POTENTIAL: inferred from metrics (e.g. low CPU); needs human review."""

    CONFIRMED = "confirmed"
    POTENTIAL = "potential"


class CostBasis(StrEnum):
    ACTUAL_COST = "actual_cost"  # trailing cost from Cost Management
    RETAIL_PRICE = "retail_price"  # Azure Retail Prices API estimate
    UNAVAILABLE = "unavailable"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


class Evidence(_Frozen):
    source: str = Field(min_length=1)  # e.g. "azure-monitor", "resource-graph"
    metric: str = Field(min_length=1)
    value: float | str | None
    unit: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None


class MonthlyCost(_Frozen):
    amount: Decimal | None  # None when no defensible number exists
    currency: str | None
    basis: CostBasis

    @field_validator("amount")
    @classmethod
    def _non_negative(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < 0:
            raise ValueError("amount must be >= 0")
        return v


class Finding(_Frozen):
    resource_id: str
    name: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    resource_group: str
    subscription_id: str
    region: str
    category: str = Field(min_length=1)  # e.g. "unattached_disk"
    status: FindingStatus
    reason: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)  # no evidence, no finding
    confidence: Confidence
    monthly_cost: MonthlyCost
    recommended_action: str = Field(min_length=1)
    evidence_timestamp: datetime

    @field_validator("resource_id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        if not v.lower().startswith("/subscriptions/"):
            raise ValueError("resource_id must be an Azure resource ID")
        return v

    @field_validator("evidence_timestamp")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        return _require_aware(v)


class CostSummary(_Frozen):
    total: Decimal
    currency: str
    start_date: str
    end_date: str


class Report(_Frozen):
    schema_version: str = SCHEMA_VERSION
    generated_at: datetime
    subscription_id: str
    cost_summary: CostSummary | None
    findings: list[Finding]
    errors: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("generated_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        return _require_aware(v)

    def potential_savings_by_currency(self) -> dict[str, Decimal]:
        """Deterministic sum. Never mixes currencies; skips findings without a number."""
        totals: dict[str, Decimal] = {}
        for f in self.findings:
            c = f.monthly_cost
            if c.amount is None or c.currency is None:
                continue
            totals[c.currency] = totals.get(c.currency, Decimal(0)) + c.amount
        return totals
