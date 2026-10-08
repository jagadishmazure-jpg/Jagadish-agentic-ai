// Opt-in Microsoft Defender for Cloud plans (Standard tier). SUBSCRIPTION-WIDE and billed per
// protected resource, so main.bicep deploys this module only when enableDefender = true.
// Mirrors infra/terraform/modules/defender. Not deployed.
targetScope = 'subscription'

@description('Defender for Cloud plan names, for example AI, KeyVaults, Arm.')
param plans array

@batchSize(1) // pricings on one subscription must be updated one at a time
resource pricing 'Microsoft.Security/pricings@2024-01-01' = [for plan in plans: {
  name: plan
  properties: { pricingTier: 'Standard' }
}]

output plans array = plans
