variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "name" {
  type = string
}

variable "tenant_id" {
  type = string
}

variable "soft_delete_retention_days" {
  type    = number
  default = 7
}

variable "purge_protection_enabled" {
  type    = bool
  default = false
}

variable "public_network_access_enabled" {
  type    = bool
  default = true
}

variable "secret_reader_principal_ids" {
  description = "static key -> principal id granted Key Vault Secrets User"
  type        = map(string)
  default     = {}
}
