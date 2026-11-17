locals {
  tags = {
    env           = var.environment
    owner         = var.owner
    project       = "agentic-ai-portfolio"
    "cost-center" = "portfolio"
    service       = "it-desk-playbook"
    "managed-by"  = "terraform"
  }

  log_group_name = "/it-desk/playbook"
  account_id     = data.aws_caller_identity.current.account_id

  foundation_model_arns = [
    "arn:aws:bedrock:${var.region}::foundation-model/${var.bedrock_model_id}",
    "arn:aws:bedrock:${var.region}::foundation-model/${var.llama_model_id}",
  ]
  inference_profile_arns = [
    for id in var.inference_profile_ids :
    "arn:aws:bedrock:${var.region}:${local.account_id}:inference-profile/${id}"
  ]
  model_arns = concat(local.foundation_model_arns, local.inference_profile_arns)

  container_env = {
    IT_DESK_PROVIDER  = var.enable_live_model ? "bedrock" : "mock"
    BEDROCK_MODEL_ID  = var.bedrock_model_id
    IT_DESK_LOG_GROUP = local.log_group_name
    IT_DESK_LOG_MODE  = "cloudwatch"
  }
}

data "aws_caller_identity" "current" {}
