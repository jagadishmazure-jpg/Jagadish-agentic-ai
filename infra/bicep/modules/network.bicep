// Optional private networking (privateNetworking=true): VNet with a Container Apps infrastructure
// subnet and a private-endpoint subnet, one NSG on both, and private DNS zones linked to the VNet.
// Mirrors infra/terraform/modules/network. Not deployed.
param location string
param tags object
param name string
param addressPrefix string = '10.40.0.0/16'
@description('Private DNS zones: [{ key, zone }]')
param dnsZones array

// One NSG for both subnets (default rules only; tighten per client policy), as in Terraform.
resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: 'nsg-${name}'
  location: location
  tags: tags
  properties: { securityRules: [] }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: [addressPrefix] }
    subnets: [
      {
        name: 'aca'
        properties: {
          addressPrefix: cidrSubnet(addressPrefix, 23, 0)
          networkSecurityGroup: { id: nsg.id }
          delegations: [{ name: 'aca', properties: { serviceName: 'Microsoft.App/environments' } }]
        }
      }
      {
        name: 'pe'
        properties: { addressPrefix: cidrSubnet(addressPrefix, 24, 2), networkSecurityGroup: { id: nsg.id }, privateEndpointNetworkPolicies: 'Disabled' }
      }
    ]
  }
}

resource dns 'Microsoft.Network/privateDnsZones@2020-06-01' = [for z in dnsZones: {
  name: z.zone
  location: 'global'
  tags: tags
}]

resource links 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = [for (z, i) in dnsZones: {
  parent: dns[i]
  name: 'link-${name}'
  location: 'global'
  properties: { virtualNetwork: { id: vnet.id }, registrationEnabled: false }
}]

output vnetId string = vnet.id
output nsgId string = nsg.id
output acaSubnetId string = vnet.properties.subnets[0].id
output peSubnetId string = vnet.properties.subnets[1].id
output zoneIds object = toObject(dnsZones, z => z.key, z => resourceId('Microsoft.Network/privateDnsZones', z.zone))
