"""Resource Graph (KQL) queries. Read-only by construction: Resource Graph cannot write.

NOTE: field names follow the documented ARG schema but have not been run against a live
subscription yet; the opt-in live test (later phase) is what verifies them.
"""

DISKS = """Resources
| where type =~ 'microsoft.compute/disks'
| where isempty(managedBy)
| where tostring(properties.diskState) =~ 'Unattached'
| project id, name, resourceGroup, subscriptionId, location,
    skuName = tostring(sku.name),
    sizeGb = toint(properties.diskSizeGB),
    diskState = tostring(properties.diskState),
    timeCreated = tostring(properties.timeCreated),
    managedBy = tostring(managedBy)"""

PUBLIC_IPS = """Resources
| where type =~ 'microsoft.network/publicipaddresses'
| where isempty(properties.ipConfiguration) and isempty(properties.natGateway)
| project id, name, resourceGroup, subscriptionId, location,
    skuName = tostring(sku.name),
    allocation = tostring(properties.publicIPAllocationMethod),
    ipAddress = tostring(properties.ipAddress),
    ipConfigId = tostring(properties.ipConfiguration.id),
    natGatewayId = tostring(properties.natGateway.id)"""

VMS = """Resources
| where type =~ 'microsoft.compute/virtualmachines'
| project id, name, resourceGroup, subscriptionId, location,
    vmSize = tostring(properties.hardwareProfile.vmSize),
    powerState = tostring(properties.extended.instanceView.powerState.code),
    timeCreated = tostring(properties.timeCreated)"""
