# agentic-ai-portfolio: host the LangGraph projects as one HTTP API (shared/api, root Dockerfile)
# on Azure Container Apps, with ACR, Key Vault, Application Insights and a Microsoft Foundry
# (Azure OpenAI) account + project. One user-assigned identity; no keys anywhere.
data "azurerm_client_config" "current" {}

module "naming" {
  source      = "./modules/naming"
  workload    = var.workload
  environment = var.environment
  location    = var.location
  instance    = var.instance
  suffix      = var.name_suffix
}

resource "azurerm_resource_group" "this" {
  name     = module.naming.resource_group
  location = var.location
  tags     = local.tags
}

module "identity" {
  source              = "./modules/identity"
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  tags                = local.tags
  identities          = { api = "id-api-${module.naming.base}" }
}

module "monitoring" {
  source              = "./modules/monitoring"
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  tags                = local.tags
  log_analytics_name  = module.naming.log_analytics
  app_insights_name   = module.naming.app_insights
  daily_quota_gb      = local.p.log_quota_gb
}

module "keyvault" {
  source                      = "./modules/keyvault"
  resource_group_name         = azurerm_resource_group.this.name
  location                    = var.location
  tags                        = local.tags
  name                        = module.naming.key_vault
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  purge_protection_enabled    = var.key_vault_purge_protection
  secret_reader_principal_ids = module.identity.principal_ids
  # Private networking turns public access off; the API reaches the vault through its private endpoint.
  public_network_access_enabled = !var.private_networking
}

module "registry" {
  source              = "./modules/registry"
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  tags                = local.tags
  name                = module.naming.container_registry
  pull_principal_ids  = module.identity.principal_ids
}

module "foundry" {
  source               = "./modules/foundry"
  resource_group_name  = azurerm_resource_group.this.name
  location             = var.location
  tags                 = local.tags
  name                 = local.n["aif"]
  project_name         = "agentic-portfolio"
  project_display_name = "Agentic AI portfolio"
  project_description  = "LangGraph business agents served by the portfolio API"
  chat_model_name      = var.chat_model_name
  chat_model_version   = var.chat_model_version
  chat_deployment_sku  = var.chat_deployment_sku
  chat_capacity        = local.p.capacity
  # Hard-coded public before; now follows the private networking flag (public stays the cheap default).
  public_network_access_enabled = !var.private_networking
}

# Fallback deployment for the primary -> fallback chain in shared/llm.py.
resource "azurerm_cognitive_deployment" "fallback" {
  count                = var.fallback_model_name == "" ? 0 : 1
  name                 = var.fallback_model_name
  cognitive_account_id = module.foundry.account_id

  model {
    format  = "OpenAI"
    name    = var.fallback_model_name
    version = var.fallback_model_version
  }

  sku {
    name     = var.chat_deployment_sku
    capacity = local.p.capacity
  }
}

resource "azurerm_role_assignment" "api_openai_user" {
  scope                            = module.foundry.account_id
  role_definition_name             = "Cognitive Services OpenAI User"
  principal_id                     = module.identity.principal_ids["api"]
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

module "aca_env" {
  source                     = "./modules/containerapps-env"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = var.location
  tags                       = local.tags
  name                       = module.naming.container_apps_env
  log_analytics_workspace_id = module.monitoring.log_analytics_id
  infrastructure_subnet_id   = var.private_networking ? module.network[0].aca_subnet_id : ""
}

module "api" {
  source              = "./modules/containerapp"
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.tags
  name                = "ca-api-${module.naming.base}"
  service_name        = "portfolio-api"
  environment_id      = module.aca_env.id
  identity_id         = module.identity.ids["api"]
  registry_server     = module.registry.login_server
  image               = var.container_image
  external            = true
  min_replicas        = local.p.min_replicas
  max_replicas        = local.p.max_replicas
  health_path         = "/healthz"
  env = {
    LLM_PROVIDER                          = var.live_llm ? "azure" : "mock"
    PORTFOLIO_ALLOW_LIVE                  = var.live_llm ? "1" : "0"
    AZURE_CLIENT_ID                       = module.identity.client_ids["api"]
    AZURE_OPENAI_ENDPOINT                 = module.foundry.openai_endpoint
    AZURE_OPENAI_DEPLOYMENT               = module.foundry.chat_deployment_name
    AZURE_OPENAI_FALLBACK_DEPLOYMENT      = try(azurerm_cognitive_deployment.fallback[0].name, "")
    FOUNDRY_PROJECT_ENDPOINT              = module.foundry.project_endpoint
    AZURE_KEY_VAULT_URI                   = module.keyvault.uri
    APPLICATIONINSIGHTS_CONNECTION_STRING = module.monitoring.app_insights_connection_string
  }

  depends_on = [module.registry]
}

# ---- optional private networking (off by default: private endpoints and DNS zones bill hourly) ----
module "network" {
  source              = "./modules/network"
  count               = var.private_networking ? 1 : 0
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  tags                = local.tags
  name                = module.naming.vnet
  dns_zones = {
    cognitiveservices = "privatelink.cognitiveservices.azure.com"
    openai            = "privatelink.openai.azure.com"
    aiservices        = "privatelink.services.ai.azure.com"
    keyvault          = "privatelink.vaultcore.azure.net"
  }
}

module "private_endpoint" {
  source = "./modules/private-endpoint"
  for_each = var.private_networking ? {
    foundry  = { id = module.foundry.account_id, group = "account", zones = ["cognitiveservices", "openai", "aiservices"] }
    keyvault = { id = module.keyvault.id, group = "vault", zones = ["keyvault"] }
  } : {}
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  tags                = local.tags
  name                = "pe-${each.key}-${module.naming.base}"
  subnet_id           = module.network[0].pe_subnet_id
  target_resource_id  = each.value.id
  group_id            = each.value.group
  dns_zone_ids        = [for z in each.value.zones : module.network[0].zone_ids[z]]
}

# ---- alerting, diagnostics and Defender for Cloud (written and tested offline; not deployed) ----
module "alerts" {
  source                  = "./modules/alerts"
  count                   = var.enable_alerts ? 1 : 0
  resource_group_name     = azurerm_resource_group.this.name
  location                = var.location
  tags                    = local.tags
  name_suffix             = module.naming.base
  action_group_name       = "ag-${module.naming.base}"
  action_group_short_name = "agentic"
  alert_email             = var.alert_email
  log_analytics_id        = module.monitoring.log_analytics_id
  app_insights_id         = module.monitoring.app_insights_id
  metric_alerts = {
    foundry-5xx       = { scope = module.foundry.account_id, namespace = "Microsoft.CognitiveServices/accounts", metric = "ServerErrors", aggregation = "Total", operator = "GreaterThan", threshold = 5, severity = 2, description = "Foundry model endpoint returning server errors; the fallback deployment is carrying traffic" }
    foundry-throttled = { scope = module.foundry.account_id, namespace = "Microsoft.CognitiveServices/accounts", metric = "ClientErrors", aggregation = "Total", operator = "GreaterThan", threshold = 50, severity = 3, description = "Many 4xx from Foundry (quota throttling or auth drift)" }
    kv-availability   = { scope = module.keyvault.id, namespace = "Microsoft.KeyVault/vaults", metric = "Availability", aggregation = "Average", operator = "LessThan", threshold = 99, severity = 1, description = "Key Vault availability below 99%" }
  }
  log_alerts = {
    failed-requests = { query = "requests | where success == false", threshold = 5, severity = 2, description = "More than 5 failed API requests in 15 minutes" }
    exceptions      = { query = "exceptions", threshold = 10, severity = 3, description = "Exception spike in the portfolio API" }
    dependency-fail = { query = "dependencies | where success == false", threshold = 10, severity = 3, description = "Failing calls to the model or other dependencies" }
  }
  diagnostic_targets = {
    foundry  = module.foundry.account_id
    keyvault = module.keyvault.id
    registry = module.registry.id
  }
}

module "defender" {
  source = "./modules/defender"
  count  = var.enable_defender ? 1 : 0
  plans  = var.defender_plans
}
