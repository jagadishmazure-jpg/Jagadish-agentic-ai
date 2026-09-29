# Partial backend config for dev. Create the state storage once (see ../README.md), then:
#   terraform init -backend-config=envs/dev.backend.hcl
# resource_group_name  = "rg-tfstate-shared-eus2-001"
# storage_account_name = "sttfstateshared001"
# container_name       = "tfstate"
key              = "agentic-ai-portfolio/dev.tfstate"
use_azuread_auth = true
