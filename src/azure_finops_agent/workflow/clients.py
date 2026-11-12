"""The Azure clients the workflow needs, injected as a bundle.

Tests pass fakes. Only :func:`build_azure_clients` touches the real SDK, and only the CLI calls it.
"""

from __future__ import annotations

from dataclasses import dataclass

from azure.core.credentials import TokenCredential

from ..collectors.costs import CostClient
from ..collectors.graph import GraphClient
from ..collectors.monitor import MetricsClient


@dataclass(frozen=True)
class AzureClients:
    graph: GraphClient
    monitor: MetricsClient
    cost: CostClient


def build_azure_clients(
    subscription_id: str, credential: TokenCredential | None = None
) -> AzureClients:
    """Create the real, read-only SDK clients. Constructing them makes no network call."""
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.costmanagement import CostManagementClient
    from azure.mgmt.monitor import MonitorManagementClient
    from azure.mgmt.resourcegraph import ResourceGraphClient

    cred = credential if credential is not None else DefaultAzureCredential()
    return AzureClients(
        graph=ResourceGraphClient(cred),
        monitor=MonitorManagementClient(cred, subscription_id),
        cost=CostManagementClient(cred),
    )
