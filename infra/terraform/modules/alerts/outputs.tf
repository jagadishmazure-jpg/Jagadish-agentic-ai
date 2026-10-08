output "action_group_id" {
  value = azurerm_monitor_action_group.this.id
}

output "metric_alert_names" {
  value = sort([for a in azurerm_monitor_metric_alert.this : a.name])
}

output "log_alert_names" {
  value = sort([for a in azurerm_monitor_scheduled_query_rules_alert_v2.this : a.name])
}

output "diagnostic_setting_targets" {
  value = sort(keys(azurerm_monitor_diagnostic_setting.this))
}
