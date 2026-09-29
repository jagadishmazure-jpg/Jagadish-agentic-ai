# Container registry; admin user disabled, pulls use managed identity (AcrPull).
resource "azurerm_container_registry" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
  sku                 = var.sku
  admin_enabled       = false
}

resource "azurerm_role_assignment" "pull" {
  for_each                         = var.pull_principal_ids
  scope                            = azurerm_container_registry.this.id
  role_definition_name             = "AcrPull"
  principal_id                     = each.value
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}
