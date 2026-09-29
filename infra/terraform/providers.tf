# Authentication comes from the environment: `az login` locally, or ARM_USE_OIDC=true plus
# ARM_CLIENT_ID / ARM_TENANT_ID / ARM_SUBSCRIPTION_ID in GitHub Actions (federated credential,
# no client secret).
provider "azurerm" {
  storage_use_azuread = true

  features {
    key_vault {
      purge_soft_delete_on_destroy = var.environment != "prod"
    }
    cognitive_account {
      purge_soft_delete_on_destroy = var.environment != "prod"
    }
    resource_group {
      prevent_deletion_if_contains_resources = var.environment == "prod"
    }
  }
}

provider "azapi" {}
