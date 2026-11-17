// Assessment bank: Container Apps, Cosmos DB (serverless, Entra data plane), Log Analytics.
// The Entra External ID app registration is created by the Terraform twin (Microsoft Graph).
// Bicep takes the tenant, subdomain and client id as parameters and wires the same env vars.
targetScope = 'resourceGroup'

@description('Azure region.')
param location string = 'eastus2'

@description('Environment name used in resource names.')
param environment string = 'dev'

@description('Globally unique Cosmos account name. Lowercase letters and numbers only.')
param cosmosAccountName string = 'cosmosassessdev001'

@description('Container image from assessment-bank/Dockerfile.')
param containerImage string = 'ghcr.io/example/assessment-bank:offline'

@description('External ID tenant id.')
param entraTenantId string = '00000000-0000-0000-0000-000000000001'

@description('External ID tenant subdomain. Authority host is https://<subdomain>.ciamlogin.com.')
param entraTenantSubdomain string = 'assessmentbank'

@description('Application (client) id of the External ID app registration.')
param entraClientId string = '00000000-0000-0000-0000-000000000004'

var tags = {
  env: environment
  owner: 'jagadish.meduri'
  project: 'agentic-ai-portfolio'
  'cost-center': 'portfolio'
  workload: 'assessment-bank'
  'managed-by': 'bicep'
}
var authority = 'https://${entraTenantSubdomain}.ciamlogin.com/${entraTenantId}/v2.0'
var cosmosDataContributor = '00000000-0000-0000-0000-000000000002'

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-assess-${environment}-eus2-001'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: 1 }
  }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-assess-${environment}-eus2-001'
  location: location
  tags: tags
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: cosmosAccountName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      { locationName: location, failoverPriority: 0 }
    ]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    capabilities: [
      { name: 'EnableServerless' }
    ]
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    minimalTlsVersion: 'Tls12'
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmos
  name: 'assessments'
  properties: { resource: { id: 'assessments' } }
}

resource progress 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: database
  name: 'progress'
  properties: {
    resource: {
      id: 'progress'
      partitionKey: { paths: ['/learnerId'], kind: 'Hash' }
    }
  }
}

resource sqlRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmos
  name: guid(cosmos.id, identity.id, cosmosDataContributor)
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributor}'
    principalId: identity.properties.principalId
    scope: cosmos.id
  }
}

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-assess-${environment}-eus2-001'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
  }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-assess-${environment}-eus2-001'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    environmentId: cae.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8080, transport: 'auto' }
    }
    template: {
      containers: [
        {
          name: 'main'
          image: containerImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [
            { name: 'PORT', value: '8080' }
            { name: 'ASSESSMENT_AUTH_MODE', value: 'entra' }
            { name: 'ASSESSMENT_STORE', value: 'cosmos' }
            { name: 'ENTRA_TENANT_ID', value: entraTenantId }
            { name: 'ENTRA_TENANT_SUBDOMAIN', value: entraTenantSubdomain }
            { name: 'ENTRA_AUTHORITY', value: authority }
            { name: 'ENTRA_CLIENT_ID', value: entraClientId }
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
            { name: 'COSMOS_DATABASE', value: 'assessments' }
            { name: 'COSMOS_CONTAINER', value: 'progress' }
          ]
          probes: [
            { type: 'Liveness', httpGet: { path: '/healthz', port: 8080 }, periodSeconds: 30 }
          ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 2 }
    }
  }
}

output authority string = authority
output containerAppName string = app.name
