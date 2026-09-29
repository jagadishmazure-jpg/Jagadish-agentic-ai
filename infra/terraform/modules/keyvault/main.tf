# Key Vault in RBAC mode. Purge protection is off in dev so a teardown fully cleans up;
# prod.tfvars turns it on.
resource "azurerm_key_vault" "this" {
  name                          = var.name
  resource_group_name           = var.resource_group_name
  location                      = var.location
  tags                          = var.tags
  tenant_id                     = var.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  soft_delete_retention_days    = var.soft_delete_retention_days
  purge_protection_enabled      = var.purge_protection_enabled
  public_network_access_enabled = var.public_network_access_enabled

  network_acls {
    bypass         = "AzureServices"
    default_action = var.public_network_access_enabled ? "Allow" : "Deny"
  }
}

resource "azurerm_role_assignment" "secrets_user" {
  for_each                         = var.secret_reader_principal_ids
  scope                            = azurerm_key_vault.this.id
  role_definition_name             = "Key Vault Secrets User"
  principal_id                     = each.value
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}
