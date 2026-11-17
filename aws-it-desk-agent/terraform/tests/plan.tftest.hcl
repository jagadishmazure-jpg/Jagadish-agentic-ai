# Offline plans. No AWS account, no resources created.
mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }
}

run "agentcore_stays_on_the_mock" {
  command = plan

  variables {
    compute           = "agentcore"
    enable_live_model = false
  }

  assert {
    condition     = aws_cloudwatch_log_group.agent.retention_in_days == 365 && aws_kms_key.logs.enable_key_rotation == true
    error_message = "CloudWatch log group keeps logs for 365 days and the key rotates"
  }

  assert {
    condition     = aws_bedrockagentcore_agent_runtime.this[0].environment_variables["IT_DESK_PROVIDER"] == "mock"
    error_message = "Bedrock stays off unless enable_live_model is true"
  }

  assert {
    condition     = aws_bedrockagentcore_agent_runtime.this[0].environment_variables["IT_DESK_LOG_MODE"] == "cloudwatch"
    error_message = "the runtime must log to CloudWatch"
  }

  assert {
    condition     = length(aws_ecs_service.this) == 0 && aws_ecr_repository.agent.image_tag_mutability == "IMMUTABLE"
    error_message = "the default compute is AgentCore, and image tags are immutable"
  }
}

run "fargate_defaults_to_zero_tasks" {
  command = plan

  variables {
    compute = "fargate"
  }

  assert {
    condition     = length(aws_bedrockagentcore_agent_runtime.this) == 0
    error_message = "fargate mode must not also create an AgentCore runtime"
  }

  assert {
    condition     = aws_ecs_service.this[0].desired_count == 0 && aws_ecs_cluster.this[0].name == "it-desk-playbook"
    error_message = "Fargate is defined but not started"
  }

  assert {
    condition     = alltrue([for rule in aws_security_group.task[0].egress : rule.from_port == 443 && rule.to_port == 443 && rule.protocol == "tcp"])
    error_message = "task egress is HTTPS only"
  }
}

run "live_model_is_opt_in" {
  command = plan

  variables {
    compute           = "agentcore"
    enable_live_model = true
  }

  assert {
    condition     = aws_bedrockagentcore_agent_runtime.this[0].environment_variables["IT_DESK_PROVIDER"] == "bedrock"
    error_message = "enable_live_model must set IT_DESK_PROVIDER=bedrock"
  }
}
