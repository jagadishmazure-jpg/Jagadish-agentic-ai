output "id" {
  value = azurerm_container_app.this.id
}

output "name" {
  value = azurerm_container_app.this.name
}

output "fqdn" {
  value = try(azurerm_container_app.this.ingress[0].fqdn, "")
}

output "url" {
  value = try("https://${azurerm_container_app.this.ingress[0].fqdn}", "")
}
