variable "resource_group_name" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "name" {
  type = string
}

variable "service_name" {
  description = "Logical service name, tagged on the app so the pipeline can find it."
  type        = string
}

variable "environment_id" {
  type = string
}

variable "identity_id" {
  type = string
}

variable "registry_server" {
  type = string
}

variable "image" {
  description = "Initial image; the deploy pipeline replaces it."
  type        = string
  default     = "mcr.microsoft.com/k8se/quickstart:latest"
}

variable "kind" {
  type    = string
  default = "http"
  validation {
    condition     = contains(["http", "worker"], var.kind)
    error_message = "kind must be http or worker."
  }
}

variable "external" {
  type    = bool
  default = false
}

variable "target_port" {
  type    = number
  default = 8080
}

variable "command" {
  type    = list(string)
  default = []
}

variable "env" {
  description = "Plain (non-secret) environment variables."
  type        = map(string)
  default     = {}
}

variable "health_path" {
  description = "Liveness probe path; empty disables the probe."
  type        = string
  default     = "/healthz"
}

variable "min_replicas" {
  type    = number
  default = 0
}

variable "max_replicas" {
  type    = number
  default = 3
}

variable "concurrent_requests" {
  type    = number
  default = 20
}

variable "queue_name" {
  type    = string
  default = ""
}

variable "service_bus_namespace" {
  type    = string
  default = ""
}

variable "cpu" {
  type    = number
  default = 0.5
}

variable "memory" {
  type    = string
  default = "1Gi"
}
