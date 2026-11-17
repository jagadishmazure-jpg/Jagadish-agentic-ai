variable "region" {
  type    = string
  default = "us-east-1"
}

variable "compute" {
  description = "agentcore (Bedrock AgentCore Runtime) or fargate (ECS Fargate). One is created."
  type        = string
  default     = "agentcore"

  validation {
    condition     = contains(["agentcore", "fargate"], var.compute)
    error_message = "compute must be agentcore or fargate."
  }
}

variable "enable_live_model" {
  description = "When false the container stays on the deterministic mock. Bedrock is opt-in."
  type        = bool
  default     = false
}

variable "bedrock_model_id" {
  description = "Claude on Bedrock. Llama is also allowed by the IAM policy; switch with BEDROCK_MODEL_ID."
  type        = string
  default     = "anthropic.claude-3-5-haiku-20241022-v1:0"
}

variable "llama_model_id" {
  type    = string
  default = "meta.llama3-1-8b-instruct-v1:0"
}

variable "inference_profile_ids" {
  description = "Cross-region inference profiles the task may invoke, in addition to the foundation models."
  type        = list(string)
  default = [
    "us.anthropic.claude-3-5-haiku-20241022-v1:0",
    "us.meta.llama3-1-8b-instruct-v1:0",
  ]
}

variable "image_tag" {
  description = "Tag in this stack's ECR repository. Push an arm64 image before an AgentCore apply."
  type        = string
  default     = "offline"
}

variable "fargate_desired_count" {
  description = "Fargate tasks to run. Zero keeps the service defined and the bill at zero."
  type        = number
  default     = 0
}

variable "log_retention_days" {
  type    = number
  default = 365
}

variable "owner" {
  type    = string
  default = "jagadish.meduri"
}

variable "environment" {
  type    = string
  default = "dev"
}
