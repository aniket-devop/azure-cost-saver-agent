"""The Azure clients the workflow needs, injected as a bundle.

Tests pass fakes. Only :func:`build_azure_clients` touches the real SDK, and only the CLI calls it.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from azure.core.credentials import AccessToken, TokenCredential

from ..collectors.costs import CostClient
from ..collectors.graph import GraphClient
from ..collectors.monitor import MetricsClient

MANAGEMENT_SCOPE = "https://management.azure.com/.default"
# `az account get-access-token` can take 30s+ on slow machines; the SDK default is only 10s.
CLI_PROCESS_TIMEOUT_S = 120


@dataclass(frozen=True)
class AzureClients:
    graph: GraphClient
    monitor: MetricsClient
    cost: CostClient
    warm_up: Callable[[], None] | None = None  # fetch the token once, fail fast on bad login


class CachingCredential:
    """Shares one token per scope across every client and thread.

    Without this, each parallel collector may start its own slow ``az`` process. One lock means
    one fetch; everyone else reuses the result until shortly before it expires.
    """

    def __init__(
        self,
        inner: TokenCredential,
        *,
        margin_s: float = 300.0,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._inner = inner
        self._margin_s = margin_s
        self._now = now
        self._lock = threading.Lock()
        self._cache: dict[tuple[tuple[str, ...], str | None], AccessToken] = {}

    def get_token(
        self,
        *scopes: str,
        claims: str | None = None,
        tenant_id: str | None = None,
        enable_cae: bool = False,
        **kwargs: Any,
    ) -> AccessToken:
        if claims or enable_cae:  # special requests are never served from the cache
            return self._inner.get_token(
                *scopes, claims=claims, tenant_id=tenant_id, enable_cae=enable_cae, **kwargs
            )
        key = (scopes, tenant_id)
        with self._lock:
            token = self._cache.get(key)
            if token is None or token.expires_on - self._now() < self._margin_s:
                token = self._inner.get_token(*scopes, tenant_id=tenant_id, **kwargs)
                self._cache[key] = token
            return token


def build_azure_clients(
    subscription_id: str, credential: TokenCredential | None = None
) -> AzureClients:
    """Create the real, read-only SDK clients. Constructing them makes no network call."""
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.costmanagement import CostManagementClient
    from azure.mgmt.monitor import MonitorManagementClient
    from azure.mgmt.resourcegraph import ResourceGraphClient

    base = (
        credential
        if credential is not None
        else DefaultAzureCredential(process_timeout=CLI_PROCESS_TIMEOUT_S)
    )
    cred = CachingCredential(base)

    def warm_up() -> None:
        cred.get_token(MANAGEMENT_SCOPE)

    return AzureClients(
        graph=ResourceGraphClient(cred),
        monitor=MonitorManagementClient(cred, subscription_id),
        cost=CostManagementClient(cred),
        warm_up=warm_up,
    )
