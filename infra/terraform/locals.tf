locals {
  profiles = {
    "cost-min" = { min_replicas = 0, max_replicas = 2, log_quota_gb = 1, capacity = 10 }
    standard   = { min_replicas = 1, max_replicas = 5, log_quota_gb = -1, capacity = 50 }
  }
  p = local.profiles[var.cost_profile]
  n = module.naming.prefix_for

  tags = merge({
    env            = var.environment
    owner          = var.owner
    project        = var.project
    "cost-center"  = var.cost_center
    workload       = var.workload
    "cost-profile" = var.cost_profile
    "managed-by"   = "terraform"
  }, var.extra_tags)
}
