data "azuread_client_config" "current" {}

locals {
  tags = {
    env           = var.environment
    owner         = var.owner
    project       = "agentic-ai-portfolio"
    "cost-center" = "portfolio"
    workload      = "assessment-bank"
    "managed-by"  = "terraform"
  }
  tenant_id = var.entra_tenant_id != "" ? var.entra_tenant_id : data.azuread_client_config.current.tenant_id
  authority = "https://${var.entra_tenant_subdomain}.ciamlogin.com/${local.tenant_id}/v2.0"
}

resource "azurerm_resource_group" "this" {
  name     = "rg-assess-${var.environment}-eus2-001"
  location = var.location
  tags     = local.tags
}

resource "azurerm_log_analytics_workspace" "this" {
  name                = "log-assess-${var.environment}-eus2-001"
  location            = var.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 1
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "app" {
  name                = "id-assess-${var.environment}-eus2-001"
  location            = var.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.tags
}

resource "azuread_application" "assessment" {
  display_name     = "assessment-bank"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azuread_client_config.current.object_id]

  single_page_application {
    redirect_uris = var.spa_redirect_uris
  }

  api {
    requested_access_token_version = 2
  }
}

resource "azurerm_cosmosdb_account" "this" {
  name                          = var.cosmos_account_name
  location                      = var.location
  resource_group_name           = azurerm_resource_group.this.name
  offer_type                    = "Standard"
  kind                          = "GlobalDocumentDB"
  automatic_failover_enabled    = false
  local_authentication_enabled  = false
  public_network_access_enabled = true
  minimal_tls_version           = "Tls12"
  tags                          = local.tags

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = var.location
    failover_priority = 0
  }

  capabilities {
    name = "EnableServerless"
  }
}

resource "azurerm_cosmosdb_sql_database" "this" {
  name                = "assessments"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.this.name
}

resource "azurerm_cosmosdb_sql_container" "progress" {
  name                = "progress"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.this.name
  database_name       = azurerm_cosmosdb_sql_database.this.name
  partition_key_paths = ["/learnerId"]
}

resource "azurerm_cosmosdb_sql_role_assignment" "app" {
  name                = "6f9e1c0a-7b2d-4e5f-9a10-0b1c2d3e4f50"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.this.name
  role_definition_id  = "${azurerm_cosmosdb_account.this.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_user_assigned_identity.app.principal_id
  scope               = azurerm_cosmosdb_account.this.id
}

resource "azurerm_container_app_environment" "this" {
  name                       = "cae-assess-${var.environment}-eus2-001"
  location                   = var.location
  resource_group_name        = azurerm_resource_group.this.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
  tags                       = local.tags

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

resource "azurerm_container_app" "this" {
  name                         = "ca-assess-${var.environment}-eus2-001"
  resource_group_name          = azurerm_resource_group.this.name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  template {
    min_replicas = 0
    max_replicas = 2

    container {
      name   = "main"
      image  = var.container_image
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "PORT"
        value = "8080"
      }
      env {
        name  = "ASSESSMENT_AUTH_MODE"
        value = "entra"
      }
      env {
        name  = "ASSESSMENT_STORE"
        value = "cosmos"
      }
      env {
        name  = "ENTRA_TENANT_ID"
        value = local.tenant_id
      }
      env {
        name  = "ENTRA_TENANT_SUBDOMAIN"
        value = var.entra_tenant_subdomain
      }
      env {
        name  = "ENTRA_AUTHORITY"
        value = local.authority
      }
      env {
        name  = "ENTRA_CLIENT_ID"
        value = azuread_application.assessment.client_id
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.app.client_id
      }
      env {
        name  = "COSMOS_ENDPOINT"
        value = azurerm_cosmosdb_account.this.endpoint
      }
      env {
        name  = "COSMOS_DATABASE"
        value = azurerm_cosmosdb_sql_database.this.name
      }
      env {
        name  = "COSMOS_CONTAINER"
        value = azurerm_cosmosdb_sql_container.progress.name
      }

      liveness_probe {
        transport        = "HTTP"
        port             = 8080
        path             = "/healthz"
        interval_seconds = 30
        timeout          = 3
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8080
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}
