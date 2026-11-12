"""DEPRECATED (Phase 5): legacy module kept temporarily; do not use in new code.

Superseded by the azure_finops_agent package (run: azure-finops run). The new LangGraph
workflow never imports this module. Known problems: hardcoded or guessed figures and no
partial-result handling. Scheduled for removal once the Azure Functions entry point is
migrated.
"""
import warnings

warnings.warn(
    "mcp_server.py is deprecated; use the azure_finops_agent package (azure-finops run)",
    DeprecationWarning,
    stacklevel=2,
)

from mcp.server.fastmcp import FastMCP
from cost_fetcher import get_last_7_days_cost
from idle_finder import find_idle_resources

mcp = FastMCP("azure-cost-tools")


@mcp.tool()
def get_cost_last_7_days() -> dict:
    """Get total Azure cost for the last 7 days."""
    return get_last_7_days_cost()


@mcp.tool()
def find_idle_azure_resources() -> list:
    """Find idle VMs (avg CPU under 5%), unattached disks and unattached public IPs, with estimated monthly waste in INR."""
    return find_idle_resources()


if __name__ == "__main__":
    mcp.run()
