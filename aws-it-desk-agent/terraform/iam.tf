# Execution role for Bedrock AgentCore Runtime. Trust is limited to this account so another
# account's runtime cannot assume it. Model invoke is limited to the Claude and Llama ARNs.
# Policies are jsonencode'd so `terraform test` (which mocks AWS data sources) can still plan.
locals {
  agentcore_assume = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "bedrock-agentcore.amazonaws.com"
      }
      Action = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:aws:bedrock-agentcore:${var.region}:${local.account_id}:runtime/*" }
      }
    }]
  })

  ecs_assume = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  task_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ECRImage"
        Effect   = "Allow"
        Action   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
        Resource = [aws_ecr_repository.agent.arn]
      },
      {
        # GetAuthorizationToken does not accept a repository ARN.
        Sid      = "ECRToken"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "PlaybookLogs"
        Effect = "Allow"
        Action = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
        Resource = [
          aws_cloudwatch_log_group.agent.arn,
          "${aws_cloudwatch_log_group.agent.arn}:*",
        ]
      },
      {
        Sid    = "AgentCoreRuntimeLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:DescribeLogStreams",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = [
          "arn:aws:logs:${var.region}:${local.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*",
          "arn:aws:logs:${var.region}:${local.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*",
        ]
      },
      {
        Sid      = "BedrockModels"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = local.model_arns
      },
    ]
  })
}

resource "aws_iam_role" "agentcore" {
  count              = var.compute == "agentcore" ? 1 : 0
  name               = "it-desk-agentcore"
  assume_role_policy = local.agentcore_assume
}

resource "aws_iam_role_policy" "agentcore" {
  count  = var.compute == "agentcore" ? 1 : 0
  name   = "it-desk-agentcore"
  role   = aws_iam_role.agentcore[0].id
  policy = local.task_policy
}

resource "aws_iam_role" "fargate_execution" {
  count              = var.compute == "fargate" ? 1 : 0
  name               = "it-desk-fargate-execution"
  assume_role_policy = local.ecs_assume
}

resource "aws_iam_role_policy" "fargate_execution" {
  count  = var.compute == "fargate" ? 1 : 0
  name   = "it-desk-fargate-execution"
  role   = aws_iam_role.fargate_execution[0].id
  policy = local.task_policy
}

resource "aws_iam_role" "fargate_task" {
  count              = var.compute == "fargate" ? 1 : 0
  name               = "it-desk-fargate-task"
  assume_role_policy = local.ecs_assume
}

resource "aws_iam_role_policy" "fargate_task" {
  count  = var.compute == "fargate" ? 1 : 0
  name   = "it-desk-fargate-task"
  role   = aws_iam_role.fargate_task[0].id
  policy = local.task_policy
}
