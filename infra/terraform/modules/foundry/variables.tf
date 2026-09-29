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
  description = "Account name; also used as the custom subdomain."
  type        = string
}

variable "project_name" {
  type = string
}

variable "project_display_name" {
  type    = string
  default = "Agent project"
}

variable "project_description" {
  type    = string
  default = ""
}

variable "chat_model_name" {
  type = string
}

variable "chat_model_version" {
  type = string
}

variable "chat_deployment_sku" {
  type    = string
  default = "GlobalStandard"
  validation {
    condition     = contains(["GlobalStandard", "DataZoneStandard", "Standard"], var.chat_deployment_sku)
    error_message = "chat_deployment_sku must be GlobalStandard, DataZoneStandard or Standard."
  }
}

variable "chat_capacity" {
  description = "Deployment capacity in thousands of tokens per minute."
  type        = number
  default     = 10
}

variable "embedding_model_name" {
  description = "Empty string = no embedding deployment."
  type        = string
  default     = ""
}

variable "embedding_model_version" {
  type    = string
  default = "1"
}

variable "embedding_capacity" {
  type    = number
  default = 10
}

variable "search_endpoint" {
  type    = string
  default = ""
}

variable "connect_search" {
  description = "Create the project connection to AI Search (needs search_endpoint + search_resource_id)."
  type        = bool
  default     = false
}

variable "search_resource_id" {
  type    = string
  default = ""
}

variable "public_network_access_enabled" {
  type    = bool
  default = true
}
