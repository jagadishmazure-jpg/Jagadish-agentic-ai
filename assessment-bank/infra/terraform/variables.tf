variable "environment" {
  type    = string
  default = "dev"
}

variable "location" {
  type    = string
  default = "eastus2"
}

variable "owner" {
  type    = string
  default = "jagadish.meduri"
}

variable "cosmos_account_name" {
  description = "Globally unique, lowercase letters and numbers only."
  type        = string
  default     = "cosmosassessdev001"
}

variable "container_image" {
  description = "Image built from assessment-bank/Dockerfile. Not pulled by the offline tests."
  type        = string
  default     = "ghcr.io/example/assessment-bank:offline"
}

variable "entra_tenant_subdomain" {
  description = "Host label of https://<subdomain>.ciamlogin.com for the External ID tenant."
  type        = string
  default     = "assessmentbank"
}

variable "entra_tenant_id" {
  description = "External ID tenant id. Empty uses the tenant of the azuread provider."
  type        = string
  default     = ""
}

variable "spa_redirect_uris" {
  type    = list(string)
  default = ["http://localhost:8080/"]
}
