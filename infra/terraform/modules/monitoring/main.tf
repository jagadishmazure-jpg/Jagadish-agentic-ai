# Log Analytics (pay-per-GB, optional daily cap) + workspace-based Application Insights.
resource "azurerm_log_analytics_workspace" "this" {
  name                = var.log_analytics_name
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
  sku                 = "PerGB2018"
  retention_in_days   = var.retention_in_days
  daily_quota_gb      = var.daily_quota_gb
}

resource "azurerm_application_insights" "this" {
  name                = var.app_insights_name
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.this.id
  # Connection-string ingestion for the OpenTelemetry distro; set false and use MI auth for hardened prod.
  local_authentication_enabled = var.local_authentication_enabled
}
