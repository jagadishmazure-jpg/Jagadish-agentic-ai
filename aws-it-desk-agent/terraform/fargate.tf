# Optional ECS Fargate home for the same image and the same CloudWatch log group.
# Public IP and port 8080 are a demo trade-off so the task can reach Bedrock without a NAT
# gateway. desired_count defaults to 0, so a plan does not start a task.
resource "aws_vpc" "this" {
  count                = var.compute == "fargate" ? 1 : 0
  cidr_block           = "10.20.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
}

resource "aws_internet_gateway" "this" {
  count  = var.compute == "fargate" ? 1 : 0
  vpc_id = aws_vpc.this[0].id
}

resource "aws_subnet" "public" {
  count                   = var.compute == "fargate" ? 2 : 0
  vpc_id                  = aws_vpc.this[0].id
  cidr_block              = cidrsubnet("10.20.0.0/16", 8, count.index + 1)
  availability_zone       = "${var.region}${count.index == 0 ? "a" : "b"}"
  map_public_ip_on_launch = true
}

resource "aws_route_table" "public" {
  count  = var.compute == "fargate" ? 1 : 0
  vpc_id = aws_vpc.this[0].id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this[0].id
  }
}

resource "aws_route_table_association" "public" {
  count          = var.compute == "fargate" ? 2 : 0
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}

resource "aws_security_group" "task" {
  count       = var.compute == "fargate" ? 1 : 0
  name        = "it-desk-playbook"
  description = "IT desk agent. Egress is HTTPS only."
  vpc_id      = aws_vpc.this[0].id

  ingress {
    description = "Agent HTTP while a task is running"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Bedrock, ECR and CloudWatch"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecs_cluster" "this" {
  count = var.compute == "fargate" ? 1 : 0
  name  = "it-desk-playbook"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_task_definition" "this" {
  count                    = var.compute == "fargate" ? 1 : 0
  family                   = "it-desk-playbook"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.fargate_execution[0].arn
  task_role_arn            = aws_iam_role.fargate_task[0].arn

  container_definitions = jsonencode([
    {
      name      = "it-desk"
      image     = "${aws_ecr_repository.agent.repository_url}:${var.image_tag}"
      essential = true
      portMappings = [
        { containerPort = 8080, protocol = "tcp" }
      ]
      environment = [
        for key, value in local.container_env : { name = key, value = value }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.agent.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "this" {
  count           = var.compute == "fargate" ? 1 : 0
  name            = "it-desk-playbook"
  cluster         = aws_ecs_cluster.this[0].id
  task_definition = aws_ecs_task_definition.this[0].arn
  desired_count   = var.fargate_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.task[0].id]
    assign_public_ip = true
  }
}
