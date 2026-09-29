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

variable "log_analytics_name" {
  type = string
}

variable "app_insights_name" {
  type = string
}

variable "retention_in_days" {
  type    = number
  default = 30
}

variable "daily_quota_gb" {
  description = "Daily ingestion cap in GB; -1 = no cap. The cost-min profile uses 1."
  type        = number
  default     = 1
}

variable "local_authentication_enabled" {
  type    = bool
  default = true
}
