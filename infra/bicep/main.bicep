// agentic-ai-portfolio: Bicep twin of infra/terraform. Hosts the portfolio API (shared/api, root
// Dockerfile) on Azure Container Apps with ACR, Key Vault, Application Insights and a Microsoft
// Foundry (Azure OpenAI) account + project. Resource-group scope; the pipeline creates the group.
//   az deployment group create -g rg-agentic-dev-eus2-001 -f infra/bicep/main.bicep -p environment=dev
targetScope = 'resourceGroup'

@allowed(['dev', 'test', 'prod'])
param environment string
param location string = resourceGroup().location
@maxLength(12)
param workload string = 'agentic'
param instance string = '001'
@description('Optional suffix for globally unique names (set when forking).')
param nameSuffix string = ''
param owner string = 'jagadish.meduri'
param costCenter string = 'portfolio'
@allowed(['cost-min', 'standard'])
param costProfile string = environment == 'prod' ? 'standard' : 'cost-min'
param chatModelName string = 'gpt-5-mini'
param chatModelVersion string = '2025-08-07'
@allowed(['GlobalStandard', 'DataZoneStandard', 'Standard'])
param chatDeploymentSku string = 'GlobalStandard'
@description('Second deployment for the primary -> fallback chain; empty = none.')
param fallbackModelName string = 'gpt-4.1-mini'
param fallbackModelVersion string = '2025-04-14'
@description('Switch from the offline mock to the Foundry deployment (needs keyless auth in shared/llm.py).')
param liveLlm bool = false
param keyVaultPurgeProtection bool = environment == 'prod'
param containerImage string = 'mcr.microsoft.com/k8se/quickstart:latest'
@description('Opt-in: VNet with an NSG, private endpoints for Foundry and Key Vault, public access off on both, VNet-integrated Container Apps environment. Off by default (private endpoints and DNS zones bill hourly).')
param privateNetworking bool = false
@description('Action group, metric + log alert rules and diagnostic settings to Log Analytics. Cheap; on by default.')
param enableAlerts bool = true
@description('Optional on-call email for the action group. Empty = alerts fire in Azure Monitor only.')
param alertEmail string = ''
@description('Opt-in: Microsoft Defender for Cloud plans. SUBSCRIPTION-WIDE and billed per resource, so off by default.')
param enableDefender bool = false
param defenderPlans array = ['AI', 'Arm', 'KeyVaults']

var regionShort = {
  eastus: 'eus'
  eastus2: 'eus2'
  westus2: 'wus2'
  westus3: 'wus3'
  centralus: 'cus'
  swedencentral: 'sdc'
  westeurope: 'weu'
  northeurope: 'neu'
  uksouth: 'uks'
}[?location] ?? take(location, 6)
var base = '${workload}-${environment}-${regionShort}-${instance}'
var sfx = empty(nameSuffix) ? '' : '-${nameSuffix}'
var profiles = {
  'cost-min': { minReplicas: 0, maxReplicas: 2, logQuotaGb: 1, capacity: 10 }
  standard: { minReplicas: 1, maxReplicas: 5, logQuotaGb: -1, capacity: 50 }
}
var p = profiles[costProfile]
var publicAccess = privateNetworking ? 'Disabled' : 'Enabled'
var tags = {
  env: environment
  owner: owner
  project: 'agentic-ai-portfolio'
  'cost-center': costCenter
  workload: workload
  'cost-profile': costProfile
  'managed-by': 'bicep'
}
var roleIds = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  openAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-api-${base}'
  location: location
  tags: tags
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${base}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: p.logQuotaGb }
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${base}'
  location: location
  tags: tags
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id }
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: take('kv-${workload}-${environment}-${instance}${sfx}', 24)
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enablePurgeProtection: keyVaultPurgeProtection ? true : null
    // Private networking turns public access off; the API reaches the vault through its private endpoint.
    publicNetworkAccess: publicAccess
    networkAcls: { bypass: 'AzureServices', defaultAction: privateNetworking ? 'Deny' : 'Allow' }
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'cr${workload}${environment}${regionShort}${instance}${nameSuffix}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'aif-${base}${sfx}'
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    allowProjectManagement: true
    customSubDomainName: 'aif-${base}${sfx}'
    disableLocalAuth: true
    // Was hard-coded 'Enabled'; now follows privateNetworking (public stays the cheap default).
    publicNetworkAccess: publicAccess
    networkAcls: { defaultAction: privateNetworking ? 'Deny' : 'Allow' }
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: 'agentic-portfolio'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Agentic AI portfolio'
    description: 'LangGraph business agents served by the portfolio API'
  }
}

resource chat 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: chatModelName
  sku: { name: chatDeploymentSku, capacity: p.capacity }
  properties: {
    model: { format: 'OpenAI', name: chatModelName, version: chatModelVersion }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

resource fallback 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = if (!empty(fallbackModelName)) {
  parent: foundry
  name: empty(fallbackModelName) ? 'none' : fallbackModelName
  sku: { name: chatDeploymentSku, capacity: p.capacity }
  properties: {
    model: { format: 'OpenAI', name: fallbackModelName, version: fallbackModelVersion }
  }
  dependsOn: [chat] // deployments on one account are serialized
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, identity.id, roleIds.acrPull)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.acrPull)
  }
}

resource kvSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, identity.id, roleIds.keyVaultSecretsUser)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.keyVaultSecretsUser)
  }
}

resource openAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, identity.id, roleIds.openAiUser)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.openAiUser)
  }
}

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${base}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: logs.properties.customerId, sharedKey: logs.listKeys().primarySharedKey }
    }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
    vnetConfiguration: privateNetworking ? { infrastructureSubnetId: network!.outputs.acaSubnetId, internal: false } : null
  }
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-api-${base}'
  location: location
  tags: union(tags, { 'service-name': 'portfolio-api' })
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    environmentId: cae.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8080, transport: 'auto' }
      registries: [{ server: acr.properties.loginServer, identity: identity.id }]
    }
    template: {
      containers: [
        {
          name: 'main'
          image: containerImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'PORT', value: '8080' }
            { name: 'LLM_PROVIDER', value: liveLlm ? 'azure' : 'mock' }
            { name: 'PORTFOLIO_ALLOW_LIVE', value: liveLlm ? '1' : '0' }
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'AZURE_OPENAI_ENDPOINT', value: 'https://${foundry.properties.customSubDomainName}.openai.azure.com/' }
            { name: 'AZURE_OPENAI_DEPLOYMENT', value: chat.name }
            { name: 'AZURE_OPENAI_FALLBACK_DEPLOYMENT', value: empty(fallbackModelName) ? '' : fallbackModelName }
            { name: 'FOUNDRY_PROJECT_ENDPOINT', value: project.properties.endpoints['AI Foundry API'] }
            { name: 'AZURE_KEY_VAULT_URI', value: kv.properties.vaultUri }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appi.properties.ConnectionString }
          ]
          probes: [{ type: 'Liveness', httpGet: { path: '/healthz', port: 8080 }, periodSeconds: 30 }]
        }
      ]
      scale: {
        minReplicas: p.minReplicas
        maxReplicas: p.maxReplicas
        rules: [{ name: 'http', http: { metadata: { concurrentRequests: '20' } } }]
      }
    }
  }
  dependsOn: [acrPull, fallback]
}

// ---- optional private networking (off by default) ----
module network 'modules/network.bicep' = if (privateNetworking) {
  name: 'network'
  params: {
    location: location
    tags: tags
    name: 'vnet-${base}'
    dnsZones: [
      { key: 'cognitiveservices', zone: 'privatelink.cognitiveservices.azure.com' }
      { key: 'openai', zone: 'privatelink.openai.azure.com' }
      { key: 'aiservices', zone: 'privatelink.services.ai.azure.com' }
      { key: 'keyvault', zone: 'privatelink.vaultcore.azure.net' }
    ]
  }
}

var peTargets = [
  { name: 'foundry', id: foundry.id, group: 'account', zones: ['cognitiveservices', 'openai', 'aiservices'] }
  { name: 'keyvault', id: kv.id, group: 'vault', zones: ['keyvault'] }
]

module privateEndpoints 'modules/private-endpoint.bicep' = [for pe in (privateNetworking ? peTargets : []): {
  name: 'pe-${pe.name}'
  params: {
    location: location
    tags: tags
    name: 'pe-${pe.name}-${base}'
    subnetId: network!.outputs.peSubnetId
    targetResourceId: pe.id
    groupId: pe.group
    dnsZoneIds: map(pe.zones, z => network!.outputs.zoneIds[z])
  }
}]

// ---- alerting, diagnostics and Defender for Cloud (built offline; not deployed) ----
module alerts 'modules/alerts.bicep' = if (enableAlerts) {
  name: 'alerts'
  params: {
    location: location
    tags: tags
    resourceToken: base
    actionGroupShortName: 'agentic'
    alertEmail: alertEmail
    appInsightsId: appi.id
    metricAlerts: [
      { name: 'foundry-5xx', scope: foundry.id, namespace: 'Microsoft.CognitiveServices/accounts', metric: 'ServerErrors', aggregation: 'Total', operator: 'GreaterThan', threshold: 5, severity: 2, description: 'Foundry model endpoint returning server errors; the fallback deployment is carrying traffic' }
      { name: 'foundry-throttled', scope: foundry.id, namespace: 'Microsoft.CognitiveServices/accounts', metric: 'ClientErrors', aggregation: 'Total', operator: 'GreaterThan', threshold: 50, severity: 3, description: 'Many 4xx from Foundry (quota throttling or auth drift)' }
      { name: 'kv-availability', scope: kv.id, namespace: 'Microsoft.KeyVault/vaults', metric: 'Availability', aggregation: 'Average', operator: 'LessThan', threshold: 99, severity: 1, description: 'Key Vault availability below 99%' }
    ]
    logAlerts: [
      { name: 'failed-requests', query: 'requests | where success == false', threshold: 5, severity: 2, description: 'More than 5 failed API requests in 15 minutes' }
      { name: 'exceptions', query: 'exceptions', threshold: 10, severity: 3, description: 'Exception spike in the portfolio API' }
      { name: 'dependency-fail', query: 'dependencies | where success == false', threshold: 10, severity: 3, description: 'Failing calls to the model or other dependencies' }
    ]
  }
}

var diagSettings = {
  workspaceId: logs.id
  logs: [{ categoryGroup: 'allLogs', enabled: true }]
  metrics: [{ category: 'AllMetrics', enabled: true }]
}
resource diagFoundry 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableAlerts) { name: 'diag-to-law', scope: foundry, properties: diagSettings }
resource diagKv 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableAlerts) { name: 'diag-to-law', scope: kv, properties: diagSettings }
resource diagAcr 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableAlerts) { name: 'diag-to-law', scope: acr, properties: diagSettings }

module defender 'modules/defender.bicep' = if (enableDefender) {
  name: 'defender'
  scope: subscription()
  params: { plans: defenderPlans }
}

output AZURE_RESOURCE_GROUP string = resourceGroup().name
output AZURE_CONTAINER_REGISTRY_NAME string = acr.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = acr.properties.loginServer
output API_APP_NAME string = api.name
output API_URL string = 'https://${api.properties.configuration.ingress.fqdn}'
output AZURE_OPENAI_ENDPOINT string = 'https://${foundry.properties.customSubDomainName}.openai.azure.com/'
output AZURE_KEY_VAULT_URI string = kv.properties.vaultUri
