"""Environment-based configuration. Fails fast; never prints secrets."""

from __future__ import annotations

import os
from collections.abc import Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    subscription_id: str
    lookback_days: int = Field(default=7, ge=1, le=90)
    cpu_idle_threshold_pct: float = Field(default=5.0, gt=0, le=100)
    teams_webhook_url: SecretStr | None = None  # SecretStr: redacted in repr/logs


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    sub = env.get("AZURE_SUBSCRIPTION_ID", "").strip()
    if not sub:
        raise ConfigError("AZURE_SUBSCRIPTION_ID is required")
    try:
        UUID(sub)
    except ValueError as exc:
        raise ConfigError("AZURE_SUBSCRIPTION_ID must be a GUID") from exc

    raw: dict[str, object] = {"subscription_id": sub}
    if v := env.get("LOOKBACK_DAYS"):
        raw["lookback_days"] = v
    if v := env.get("CPU_IDLE_THRESHOLD_PCT"):
        raw["cpu_idle_threshold_pct"] = v
    if v := env.get("TEAMS_WEBHOOK_URL"):
        raw["teams_webhook_url"] = v
    try:
        return Settings.model_validate(raw)
    except ValidationError as exc:
        # Field names only; never echo input values (may contain secrets).
        fields = ", ".join(str(e["loc"][0]) for e in exc.errors())
        raise ConfigError(f"invalid configuration: {fields}") from exc
