variable "plans" {
  description = "Defender for Cloud plan names (resource_type values), for example AI, KeyVaults, Arm."
  type        = set(string)

  validation {
    condition     = alltrue([for p in var.plans : contains(["AI", "Api", "AppServices", "Arm", "CloudPosture", "Containers", "CosmosDbs", "Dns", "KeyVaults", "KubernetesService", "OpenSourceRelationalDatabases", "SqlServerVirtualMachines", "SqlServers", "StorageAccounts", "VirtualMachines"], p)])
    error_message = "Unknown Defender for Cloud plan name."
  }
}
