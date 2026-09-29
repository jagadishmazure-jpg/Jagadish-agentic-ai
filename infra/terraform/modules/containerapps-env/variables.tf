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

variable "log_analytics_workspace_id" {
  type = string
}

variable "infrastructure_subnet_id" {
  description = "Empty = public environment without VNet integration."
  type        = string
  default     = ""
}

variable "internal" {
  description = "Internal load balancer (only applies with a subnet)."
  type        = bool
  default     = false
}
