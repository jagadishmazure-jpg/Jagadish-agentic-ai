output "vnet_id" {
  value = azurerm_virtual_network.this.id
}

output "aca_subnet_id" {
  value = azurerm_subnet.aca.id
}

output "pe_subnet_id" {
  value = azurerm_subnet.pe.id
}

output "zone_ids" {
  value = { for k, z in azurerm_private_dns_zone.this : k => z.id }
}

output "nsg_id" {
  value = azurerm_network_security_group.this.id
}

output "nsg_name" {
  value = azurerm_network_security_group.this.name
}
