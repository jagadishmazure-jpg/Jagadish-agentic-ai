output "plans" {
  value = sort(keys(azurerm_security_center_subscription_pricing.this))
}
