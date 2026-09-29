output "region_short" {
  value = local.region_short
}

output "base" {
  description = "<workload>-<env>-<region>-<instance>"
  value       = local.base
}

output "suffix" {
  description = "Suffix fragment (with leading dash) for globally unique names; empty when unset."
  value       = local.sfx
}

output "resource_group" {
  value = "rg-${local.base}"
}

output "log_analytics" {
  value = "log-${local.base}"
}

output "app_insights" {
  value = "appi-${local.base}"
}

output "container_apps_env" {
  value = "cae-${local.base}"
}

output "vnet" {
  value = "vnet-${local.base}"
}

output "key_vault" {
  description = "Key Vault names are capped at 24 characters, so the region is dropped."
  value       = substr("kv-${var.workload}-${var.environment}-${var.instance}${local.sfx}", 0, 24)
}

output "container_registry" {
  value = substr("cr${local.alnum}", 0, 50)
}

output "storage_account" {
  value = substr("st${local.alnum}", 0, 24)
}

output "prefix_for" {
  description = "Helper: \"<type>-<base><suffix>\" for any resource type abbreviation."
  value       = { for t in var.types : t => "${t}-${local.base}${local.sfx}" }
}
