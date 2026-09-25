// SKELETON - not deployed. Azure Container Apps + APIM front door for the care BFF.
// Experience plane: APIM (JWT validation, per-channel/tenant rate limit) -> care-bff (external).
// Data plane: MCP servers as internal-only container apps; Service Bus replaces the in-memory outbox.
param location string = resourceGroup().location
param prefix string = 'care'
param image string // e.g. <acr>.azurecr.io/care-e2e:<sha>
param openAiEndpoint string
param openAiDeployment string
param openAiFallbackDeployment string

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs'
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: '${prefix}-appi'
  location: location
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-mi-care'
  location: location
}

resource bus 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = {
  name: '${prefix}-bus'
  location: location
  sku: { name: 'Standard' }
}

resource refundQueue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = {
  parent: bus
  name: 'refund-commands'
  properties: { requiresDuplicateDetection: true, duplicateDetectionHistoryTimeWindow: 'P1D', maxDeliveryCount: 10 }
}

var mcpApps = ['oms', 'crm', 'payments']

resource mcp 'Microsoft.App/containerApps@2024-03-01' = [for d in mcpApps: {
  name: '${prefix}-mcp-${d}'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: env.id
    configuration: { ingress: { external: false, targetPort: 8000 } } // internal only
    template: {
      containers: [{ name: 'mcp', image: image, command: ['python', '-m', 'care_e2e.mcp_main', d, '--port', '8000']
        env: [{ name: 'MCP_ALLOWED_HOSTS', value: '${prefix}-mcp-${d}*' }]
        resources: { cpu: json('0.25'), memory: '0.5Gi' } }]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
}]

resource bff 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-bff'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: env.id
    configuration: { ingress: { external: true, targetPort: 8080 } }
    template: {
      containers: [{ name: 'bff', image: image, resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'LLM_PROVIDER', value: 'azure' }
          { name: 'AZURE_OPENAI_ENDPOINT', value: openAiEndpoint }
          { name: 'AZURE_OPENAI_DEPLOYMENT', value: openAiDeployment }
          { name: 'AZURE_OPENAI_FALLBACK_DEPLOYMENT', value: openAiFallbackDeployment }
          { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId } // keyless auth
          { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appi.properties.ConnectionString }
          { name: 'CARE_MCP_URLS', value: join(map(mcpApps, d => '${d}=http://${prefix}-mcp-${d}/mcp'), ',') }
        ] }]
      scale: { minReplicas: 1, maxReplicas: 10, rules: [{ name: 'http', http: { metadata: { concurrentRequests: '30' } } }] }
    }
  }
}

resource apim 'Microsoft.ApiManagement/service@2023-05-01-preview' = {
  name: '${prefix}-apim'
  location: location
  sku: { name: 'Consumption', capacity: 0 }
  properties: { publisherEmail: 'care-platform@example.com', publisherName: 'Care Platform' }
}

resource api 'Microsoft.ApiManagement/service/apis@2023-05-01-preview' = {
  parent: apim
  name: 'care'
  properties: { path: 'care', protocols: ['https'], serviceUrl: 'https://${bff.properties.configuration.ingress.fqdn}', displayName: 'Care BFF' }
}

// Per-channel + per-tenant rate limit and JWT validation (mirrors the BFF's own checks).
resource apiPolicy 'Microsoft.ApiManagement/service/apis/policies@2023-05-01-preview' = {
  parent: api
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: '<policies><inbound><base /><validate-jwt header-name="Authorization" failed-validation-httpcode="401"><openid-config url="https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration" /></validate-jwt><rate-limit-by-key calls="20" renewal-period="60" counter-key="@(context.Request.Headers.GetValueOrDefault(&quot;X-Tenant-Id&quot;,&quot;none&quot;) + &quot;:&quot; + context.Request.MatchedParameters.GetValueOrDefault(&quot;channel&quot;,&quot;none&quot;))" /></inbound><backend><base /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>'
  }
}

output bffUrl string = 'https://${bff.properties.configuration.ingress.fqdn}'
output gatewayUrl string = apim.properties.gatewayUrl
