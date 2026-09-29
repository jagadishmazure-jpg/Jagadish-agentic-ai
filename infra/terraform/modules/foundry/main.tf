# Microsoft Foundry (new resource model): an AIServices account with project management enabled,
# one Foundry project, chat + embedding deployments, and a project connection to Azure AI Search
# using Entra ID. The project and its connection use azapi because they expose the project
# endpoint and the AAD-authenticated CognitiveSearch connection directly.
resource "azurerm_cognitive_account" "this" {
  name                          = var.name
  resource_group_name           = var.resource_group_name
  location                      = var.location
  tags                          = var.tags
  kind                          = "AIServices"
  sku_name                      = "S0"
  custom_subdomain_name         = var.name
  local_auth_enabled            = false
  project_management_enabled    = true
  public_network_access_enabled = var.public_network_access_enabled

  identity {
    type = "SystemAssigned"
  }

  network_acls {
    default_action = var.public_network_access_enabled ? "Allow" : "Deny"
  }
}

resource "azapi_resource" "project" {
  type      = "Microsoft.CognitiveServices/accounts/projects@2025-06-01"
  name      = var.project_name
  parent_id = azurerm_cognitive_account.this.id
  location  = var.location
  tags      = var.tags

  identity {
    type = "SystemAssigned"
  }

  body = {
    properties = {
      displayName = var.project_display_name
      description = var.project_description
    }
  }

  response_export_values = ["properties.endpoints"]
}

resource "azurerm_cognitive_deployment" "chat" {
  name                   = var.chat_model_name
  cognitive_account_id   = azurerm_cognitive_account.this.id
  version_upgrade_option = "OnceNewDefaultVersionAvailable"

  model {
    format  = "OpenAI"
    name    = var.chat_model_name
    version = var.chat_model_version
  }

  sku {
    name     = var.chat_deployment_sku
    capacity = var.chat_capacity
  }
}

resource "azurerm_cognitive_deployment" "embedding" {
  count                = var.embedding_model_name == "" ? 0 : 1
  name                 = var.embedding_model_name
  cognitive_account_id = azurerm_cognitive_account.this.id

  model {
    format  = "OpenAI"
    name    = var.embedding_model_name
    version = var.embedding_model_version
  }

  sku {
    name     = "Standard"
    capacity = var.embedding_capacity
  }

  # deployments on one account are serialized
  depends_on = [azurerm_cognitive_deployment.chat]
}

resource "azapi_resource" "search_connection" {
  count     = var.connect_search ? 1 : 0
  type      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01"
  name      = "aisearch"
  parent_id = azapi_resource.project.id

  body = {
    properties = {
      category      = "CognitiveSearch"
      target        = var.search_endpoint
      authType      = "AAD"
      isSharedToAll = true
      metadata = {
        ApiType    = "Azure"
        ResourceId = var.search_resource_id
      }
    }
  }
}
