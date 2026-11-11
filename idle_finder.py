import os
from datetime import datetime, timedelta, timezone
from azure.identity import DefaultAzureCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest
from azure.mgmt.monitor import MonitorManagementClient

# Rough monthly estimates in INR (MVP, hardcoded)
DISK_RATE_PER_GB = {"premium": 12, "standard": 4}
PUBLIC_IP_WASTE = 300
VM_WASTE = 2500  # flat guess per idle VM

SUB = os.environ["AZURE_SUBSCRIPTION_ID"]


def _graph(cred, query):
    client = ResourceGraphClient(cred)
    req = QueryRequest(subscriptions=[SUB], query=query)
    return client.resources(req).data


def _avg_cpu(monitor, resource_id):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    res = monitor.metrics.list(
        resource_id,
        timespan=f"{start.isoformat()}/{end.isoformat()}",
        interval="P1D",
        metricnames="Percentage CPU",
        aggregation="Average",
    )
    vals = [
        p.average
        for m in res.value
        for t in m.timeseries
        for p in t.data
        if p.average is not None
    ]
    return sum(vals) / len(vals) if vals else None


def find_idle_resources() -> list:
    cred = DefaultAzureCredential()
    monitor = MonitorManagementClient(cred, SUB)
    out = []

    # 1. Idle VMs (avg CPU < 5%)
    vms = _graph(cred, "Resources | where type =~ 'microsoft.compute/virtualmachines' | project id, name, resourceGroup, location")
    for vm in vms:
        cpu = _avg_cpu(monitor, vm["id"])
        if cpu is not None and cpu < 5:
            out.append({
                "name": vm["name"],
                "type": "VirtualMachine",
                "resource_group": vm["resourceGroup"],
                "location": vm["location"],
                "estimated_monthly_waste_inr": VM_WASTE,
            })

    # 2. Unattached disks
    disks = _graph(cred, "Resources | where type =~ 'microsoft.compute/disks' | where isempty(managedBy) | project name, resourceGroup, location, sku=tostring(sku.name), size=toint(properties.diskSizeGB)")
    for d in disks:
        rate = DISK_RATE_PER_GB["premium" if "Premium" in d["sku"] else "standard"]
        out.append({
            "name": d["name"],
            "type": "ManagedDisk",
            "resource_group": d["resourceGroup"],
            "location": d["location"],
            "estimated_monthly_waste_inr": (d["size"] or 0) * rate,
        })

    # 3. Unattached public IPs
    ips = _graph(cred, "Resources | where type =~ 'microsoft.network/publicipaddresses' | where isempty(properties.ipConfiguration) and isempty(properties.natGateway) | project name, resourceGroup, location")
    for ip in ips:
        out.append({
            "name": ip["name"],
            "type": "PublicIP",
            "resource_group": ip["resourceGroup"],
            "location": ip["location"],
            "estimated_monthly_waste_inr": PUBLIC_IP_WASTE,
        })

    return out
