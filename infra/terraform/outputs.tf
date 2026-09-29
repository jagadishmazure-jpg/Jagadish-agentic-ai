output "AZURE_RESOURCE_GROUP" {
  value = azurerm_resource_group.this.name
}

output "AZURE_CONTAINER_REGISTRY_NAME" {
  value = module.registry.name
}

output "AZURE_CONTAINER_REGISTRY_ENDPOINT" {
  value = module.registry.login_server
}

output "API_APP_NAME" {
  value = module.api.name
}

output "API_URL" {
  value = module.api.url
}

output "AZURE_OPENAI_ENDPOINT" {
  value = module.foundry.openai_endpoint
}

output "FOUNDRY_PROJECT_ENDPOINT" {
  value = module.foundry.project_endpoint
}

output "AZURE_KEY_VAULT_URI" {
  value = module.keyvault.uri
}
