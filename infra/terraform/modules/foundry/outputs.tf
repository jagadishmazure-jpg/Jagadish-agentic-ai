output "account_id" {
  value = azurerm_cognitive_account.this.id
}

output "account_name" {
  value = azurerm_cognitive_account.this.name
}

output "account_principal_id" {
  value = azurerm_cognitive_account.this.identity[0].principal_id
}

output "project_id" {
  value = azapi_resource.project.id
}

output "project_endpoint" {
  value = try(azapi_resource.project.output.properties.endpoints["AI Foundry API"], "")
}

output "openai_endpoint" {
  value = "https://${azurerm_cognitive_account.this.custom_subdomain_name}.openai.azure.com/"
}

output "chat_deployment_name" {
  value = azurerm_cognitive_deployment.chat.name
}

output "embedding_deployment_name" {
  value = try(azurerm_cognitive_deployment.embedding[0].name, "")
}

output "search_connection_name" {
  value = try(azapi_resource.search_connection[0].name, "")
}
