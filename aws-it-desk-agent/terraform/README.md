# `aws-it-desk-agent/terraform`

AWS home for the IT desk container. Default compute is Bedrock AgentCore Runtime. Set `compute = "fargate"` for ECS Fargate instead. One mode is created per apply, not both.

There is no Bicep twin: Bicep targets Azure Resource Manager, and this stack is AWS. The Azure Container Apps stack for the same agent shape stays in [`infra/`](../../infra/README.md).

Nothing has been applied. `terraform test` plans with a mocked AWS provider and does not need credentials.

| File | What it does |
|---|---|
| [`agentcore.tf`](agentcore.tf) | `aws_bedrockagentcore_agent_runtime` and a default endpoint. |
| [`ecr.tf`](ecr.tf) | ECR repository, immutable tags, scan on push, KMS encryption. |
| [`fargate.tf`](fargate.tf) | VPC, ECS cluster, task and service. `desired_count` defaults to 0. Logs use the `awslogs` driver. |
| [`iam.tf`](iam.tf) | Execution roles. Bedrock invoke is limited to the Claude and Llama model ARNs. |
| [`locals.tf`](locals.tf) | Tags, model ARNs, container env (`IT_DESK_PROVIDER` is `mock` unless `enable_live_model`). |
| [`logs.tf`](logs.tf) | KMS key and `/it-desk/playbook` with 365-day retention. |
| [`outputs.tf`](outputs.tf) | Log group, ECR URL, runtime ARN, provider env. |
| [`providers.tf`](providers.tf) | AWS provider, region from `var.region`. |
| [`tests/`](tests/README.md) | Offline plan tests. |
| [`variables.tf`](variables.tf) | Region, compute mode, live-model switch, model ids. |
| [`versions.tf`](versions.tf) | Terraform and AWS provider constraints. |
| [`.terraform.lock.hcl`](.terraform.lock.hcl) | Locked AWS provider. |

```bash
terraform -chdir=aws-it-desk-agent/terraform init -backend=false
terraform -chdir=aws-it-desk-agent/terraform test
```

Before a real apply: push an arm64 image for AgentCore, enable the model in Bedrock, and set `enable_live_model` only when you want to pay for model calls. Fargate tasks get a public IP and open port 8080 so they can reach Bedrock without a NAT gateway. Leave `fargate_desired_count` at 0 until you mean to run one.
