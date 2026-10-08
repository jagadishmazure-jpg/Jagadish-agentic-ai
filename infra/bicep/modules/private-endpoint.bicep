param location string
param tags object
param name string
param subnetId string
param targetResourceId string
param groupId string
param dnsZoneIds array

resource pe 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    subnet: { id: subnetId }
    privateLinkServiceConnections: [
      { name: name, properties: { privateLinkServiceId: targetResourceId, groupIds: [groupId] } }
    ]
  }
}

resource zoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: pe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [for (z, i) in dnsZoneIds: { name: 'z${i}', properties: { privateDnsZoneId: z } }]
  }
}
