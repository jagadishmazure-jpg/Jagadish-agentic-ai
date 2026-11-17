# Bedrock AgentCore Runtime hosts the same container ECS would. The image must be linux/arm64.
# HTTP contract: GET /ping and POST /invocations on port 8080 (it_desk.service).
resource "aws_bedrockagentcore_agent_runtime" "this" {
  count              = var.compute == "agentcore" ? 1 : 0
  agent_runtime_name = "it_desk_playbook"
  description        = "IT desk playbook agent. Mock model unless enable_live_model is true."
  role_arn           = aws_iam_role.agentcore[0].arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.agent.repository_url}:${var.image_tag}"
    }
  }

  network_configuration {
    network_mode = "PUBLIC"
  }

  # Both values are set together. A partial block has produced inconsistent plans in the provider.
  lifecycle_configuration {
    idle_runtime_session_timeout = 900
    max_lifetime                 = 28800
  }

  environment_variables = local.container_env
}

resource "aws_bedrockagentcore_agent_runtime_endpoint" "this" {
  count            = var.compute == "agentcore" ? 1 : 0
  name             = "it_desk_playbook_default"
  agent_runtime_id = aws_bedrockagentcore_agent_runtime.this[0].agent_runtime_id
}
