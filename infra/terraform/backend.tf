# Remote state in an Azure Storage account (Entra ID auth, no access keys). Partial config:
# the storage coordinates are supplied at init time, e.g.
#   terraform init -backend-config=envs/dev.backend.hcl
# Local validation skips the backend entirely:  terraform init -backend=false
terraform {
  backend "azurerm" {}
}
