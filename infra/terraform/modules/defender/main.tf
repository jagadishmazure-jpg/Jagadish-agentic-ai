# Opt-in Microsoft Defender for Cloud plans. These are SUBSCRIPTION-WIDE and billed per protected
# resource, so the root stack only calls this module when enable_defender = true. Not deployed.
resource "azurerm_security_center_subscription_pricing" "this" {
  for_each      = var.plans
  tier          = "Standard"
  resource_type = each.value
}
