variable "workload" {
  type    = string
  default = "agentic"
}

variable "environment" {
  description = "dev | test | prod"
  type        = string
}

variable "location" {
  description = "Region; must offer the chosen model SKU."
  type        = string
  default     = "eastus2"
}

variable "instance" {
  type    = string
  default = "001"
}

variable "name_suffix" {
  description = "Optional suffix for globally unique names (set when forking)."
  type        = string
  default     = ""
}

variable "owner" {
  type    = string
  default = "jagadish.meduri"
}

variable "project" {
  type    = string
  default = "agentic-ai-portfolio"
}

variable "cost_center" {
  type    = string
  default = "portfolio"
}

variable "extra_tags" {
  type    = map(string)
  default = {}
}

variable "cost_profile" {
  description = "cost-min = scale to zero, 1 GB/day logs, minimum model capacity; standard = one warm replica."
  type        = string
  default     = "cost-min"
  validation {
    condition     = contains(["cost-min", "standard"], var.cost_profile)
    error_message = "cost_profile must be cost-min or standard."
  }
}

variable "chat_model_name" {
  type    = string
  default = "gpt-5-mini"
}

variable "chat_model_version" {
  type    = string
  default = "2025-08-07"
}

variable "chat_deployment_sku" {
  type    = string
  default = "GlobalStandard"
}

variable "fallback_model_name" {
  description = "Second deployment used by the resilient LLM chain; empty = none."
  type        = string
  default     = "gpt-4.1-mini"
}

variable "fallback_model_version" {
  type    = string
  default = "2025-04-14"
}

variable "live_llm" {
  description = "Switch the API from the offline mock to the Foundry deployment (see README: needs keyless auth in shared/llm.py)."
  type        = bool
  default     = false
}

variable "key_vault_purge_protection" {
  type    = bool
  default = false
}

variable "container_image" {
  description = "Initial image; the deploy workflow rolls the portfolio API image afterwards."
  type        = string
  default     = "mcr.microsoft.com/k8se/quickstart:latest"
}
