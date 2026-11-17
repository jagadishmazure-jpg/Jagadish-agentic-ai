mock_provider "azurerm" {}

mock_provider "azuread" {
  mock_data "azuread_client_config" {
    defaults = {
      tenant_id = "00000000-0000-0000-0000-000000000001"
      object_id = "00000000-0000-0000-0000-000000000003"
      client_id = "00000000-0000-0000-0000-000000000004"
    }
  }
}

run "dev_is_entra_and_scales_to_zero" {
  command = plan

  assert {
    condition     = azurerm_container_app.this.template[0].min_replicas == 0
    error_message = "dev must scale to zero"
  }

  assert {
    condition     = azurerm_cosmosdb_account.this.local_authentication_enabled == false
    error_message = "Cosmos must use Entra data-plane auth, not account keys"
  }

  assert {
    condition     = azuread_application.assessment.display_name == "assessment-bank"
    error_message = "the External ID app registration is part of the stack"
  }

  assert {
    condition     = startswith(local.authority, "https://") && strcontains(local.authority, "ciamlogin.com")
    error_message = "learners sign in on the External ID (ciamlogin) authority"
  }
}
