output "log_analytics_id" {
  value = azurerm_log_analytics_workspace.this.id
}

output "log_analytics_name" {
  value = azurerm_log_analytics_workspace.this.name
}

output "app_insights_id" {
  value = azurerm_application_insights.this.id
}

output "app_insights_connection_string" {
  value     = azurerm_application_insights.this.connection_string
  sensitive = true
}
