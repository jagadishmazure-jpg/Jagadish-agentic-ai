variable "workload" {
  description = "Short workload token (lowercase letters/digits), e.g. agentplat."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,11}$", var.workload))
    error_message = "workload must be 2-12 lowercase letters/digits and start with a letter."
  }
}

variable "environment" {
  description = "Environment token: dev, test or prod."
  type        = string
  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment must be dev, test or prod."
  }
}

variable "location" {
  description = "Azure region name, e.g. eastus2."
  type        = string
}

variable "instance" {
  description = "Three-digit instance number."
  type        = string
  default     = "001"
  validation {
    condition     = can(regex("^[0-9]{3}$", var.instance))
    error_message = "instance must be three digits, e.g. 001."
  }
}

variable "suffix" {
  description = "Optional short suffix appended to globally unique names (set this when forking)."
  type        = string
  default     = ""
  validation {
    condition     = can(regex("^[a-z0-9]{0,6}$", var.suffix))
    error_message = "suffix must be at most 6 lowercase letters/digits."
  }
}

variable "region_abbreviations" {
  description = "Region -> short code used in names."
  type        = map(string)
  default = {
    eastus             = "eus"
    eastus2            = "eus2"
    centralus          = "cus"
    northcentralus     = "ncus"
    southcentralus     = "scus"
    westus             = "wus"
    westus2            = "wus2"
    westus3            = "wus3"
    canadacentral      = "cac"
    northeurope        = "neu"
    westeurope         = "weu"
    uksouth            = "uks"
    francecentral      = "frc"
    germanywestcentral = "gwc"
    swedencentral      = "sdc"
    switzerlandnorth   = "szn"
    australiaeast      = "aue"
    japaneast          = "jpe"
    southeastasia      = "sea"
    centralindia       = "inc"
  }
}

variable "types" {
  description = "Resource type abbreviations to pre-compute names for."
  type        = list(string)
  default     = ["id", "srch", "aif", "di", "cs", "cosmos", "sbns", "evgt", "evhns", "apim", "afd", "aks", "func", "asp", "maps", "pe", "ca", "caj"]
}
