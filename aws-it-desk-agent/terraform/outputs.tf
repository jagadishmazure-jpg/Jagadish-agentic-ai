output "log_group_name" {
  value = aws_cloudwatch_log_group.agent.name
}

output "ecr_repository_url" {
  value = aws_ecr_repository.agent.repository_url
}

output "agent_runtime_arn" {
  value = one(aws_bedrockagentcore_agent_runtime.this[*].agent_runtime_arn)
}

output "agent_runtime_endpoint" {
  value = one(aws_bedrockagentcore_agent_runtime_endpoint.this[*].agent_runtime_endpoint_arn)
}

output "ecs_cluster_name" {
  value = one(aws_ecs_cluster.this[*].name)
}

output "provider_env" {
  value = local.container_env.IT_DESK_PROVIDER
}
