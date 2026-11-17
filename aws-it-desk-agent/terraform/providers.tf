# Credentials come from the environment (AWS_PROFILE, or the task/CI role). Nothing here
# is applied by CI. `terraform test` mocks the provider.
provider "aws" {
  region = var.region

  default_tags {
    tags = local.tags
  }
}
