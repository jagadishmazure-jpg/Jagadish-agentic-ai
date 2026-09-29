# Container Apps managed environment on the Consumption workload profile (scale to zero,
# per-second billing). Optional VNet integration when private networking is on.
resource "azurerm_container_app_environment" "this" {
  name                           = var.name
  resource_group_name            = var.resource_group_name
  location                       = var.location
  tags                           = var.tags
  log_analytics_workspace_id     = var.log_analytics_workspace_id
  infrastructure_subnet_id       = var.infrastructure_subnet_id == "" ? null : var.infrastructure_subnet_id
  internal_load_balancer_enabled = var.infrastructure_subnet_id == "" ? null : var.internal

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}
