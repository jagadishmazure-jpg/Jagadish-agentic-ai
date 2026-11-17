output "authority" {
  value = local.authority
}

output "client_id" {
  value = azuread_application.assessment.client_id
}

output "cosmos_endpoint" {
  value = azurerm_cosmosdb_account.this.endpoint
}

output "container_app_name" {
  value = azurerm_container_app.this.name
}
