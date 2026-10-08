# Offline plan tests: mocked providers, no Azure credentials, nothing created.
#   terraform init -backend=false && terraform test
mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "00000000-0000-0000-0000-000000000001"
      subscription_id = "00000000-0000-0000-0000-000000000002"
      object_id       = "00000000-0000-0000-0000-000000000003"
    }
  }
}

mock_provider "azapi" {}

run "dev_cost_min" {
  command = plan

  variables {
    environment = "dev"
  }

  assert {
    condition     = azurerm_resource_group.this.name == "rg-agentic-dev-eus2-001"
    error_message = "resource group must follow the CAF pattern"
  }

  assert {
    condition     = alltrue([for k in ["env", "owner", "project", "cost-center"] : contains(keys(azurerm_resource_group.this.tags), k)])
    error_message = "required tags missing"
  }

  assert {
    condition     = local.p.min_replicas == 0 && module.api.name == "ca-api-agentic-dev-eus2-001"
    error_message = "dev must scale to zero"
  }

  assert {
    condition     = length(azurerm_cognitive_deployment.fallback) == 1
    error_message = "fallback deployment expected"
  }

  assert {
    condition     = length(module.network) == 0 && length(module.private_endpoint) == 0
    error_message = "private networking is opt-in; dev stays public for a cheap demo"
  }

  assert {
    condition     = length(module.alerts) == 1 && length(module.alerts[0].metric_alert_names) == 3 && length(module.alerts[0].log_alert_names) == 3
    error_message = "alerts are on by default: 3 metric and 3 log alert rules"
  }

  assert {
    condition     = join(",", module.alerts[0].diagnostic_setting_targets) == "foundry,keyvault,registry"
    error_message = "Foundry, Key Vault and ACR send logs and metrics to Log Analytics"
  }

  assert {
    condition     = length(module.defender) == 0
    error_message = "Defender for Cloud is subscription-wide and must stay opt-in"
  }
}

run "private_networking_and_defender" {
  command = plan

  variables {
    environment        = "prod"
    private_networking = true
    enable_defender    = true
  }

  assert {
    condition     = length(module.private_endpoint) == 2 && startswith(module.network[0].nsg_name, "nsg-")
    error_message = "private networking adds an NSG-protected VNet and private endpoints for Foundry and Key Vault"
  }

  assert {
    condition     = join(",", module.defender[0].plans) == "AI,Arm,KeyVaults"
    error_message = "enable_defender turns on the AI, Arm and KeyVaults plans"
  }
}

run "prod_standard" {
  command = plan

  variables {
    environment  = "prod"
    cost_profile = "standard"
  }

  assert {
    condition     = local.p.min_replicas == 1
    error_message = "prod keeps a warm replica"
  }
}
