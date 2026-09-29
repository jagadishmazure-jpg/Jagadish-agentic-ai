# CAF-style names: <type>-<workload>-<env>-<region>-<instance>, e.g. rg-agentplat-dev-eus2-001.
# Resources with tight length/charset rules (Key Vault, ACR, Storage) use a compressed form.
# Globally unique names take an optional suffix so a fork can deploy without collisions.

locals {
  region_short = lookup(var.region_abbreviations, var.location, substr(replace(var.location, "/[^a-z0-9]/", ""), 0, 6))
  base         = "${var.workload}-${var.environment}-${local.region_short}-${var.instance}"
  sfx          = var.suffix == "" ? "" : "-${var.suffix}"
  alnum        = replace("${var.workload}${var.environment}${local.region_short}${var.instance}${var.suffix}", "/[^a-z0-9]/", "")
}
