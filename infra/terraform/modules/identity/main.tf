# User-assigned managed identities, one per key in var.identities (static keys keep plans stable).
resource "azurerm_user_assigned_identity" "this" {
  for_each            = var.identities
  name                = each.value
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}
