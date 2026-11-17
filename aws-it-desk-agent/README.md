# IT desk playbook agent on Amazon Bedrock

There is no separate IT-desk project in this repo. The closest agent is [project 01](../projects/01-policy-qa-rag), which answers HR and IT policy questions with corrective RAG. This folder runs that same graph on an IT service-desk playbook (password reset, MFA, VPN, phishing, approved software, laptop refresh) and hosts it on AWS.

The model is a deterministic mock unless `IT_DESK_PROVIDER=bedrock`. Live calls use Amazon Bedrock InvokeModel for Claude or Llama. Terraform can place the container on **Bedrock AgentCore Runtime** (the default) or on **ECS Fargate**. Both send logs to CloudWatch. Nothing here has been applied to an AWS account.

## What a live account has to provide

CI does not call AWS. To run it for real you need:

- An AWS account, Bedrock model access for Claude 3.5 Haiku or Llama 3.1 8B in the chosen region, and an identity that can `terraform apply`.
- An **linux/arm64** image in the stack's ECR repository before an AgentCore apply (`docker buildx build --platform linux/arm64`). Fargate in this stack is x86 and can use an image built on the host.
- `IT_DESK_PROVIDER=bedrock` (the Terraform variable `enable_live_model = true` sets that). Leave it unset and the container keeps the mock.
- `IT_DESK_LOG_MODE=cloudwatch` and `IT_DESK_LOG_GROUP` (the stack sets both). Locally those stay unset and logs stay in memory plus stdout.

## Cost and latency versus the Azure version

Both clouds run this graph. The Azure version is project 01 on Azure OpenAI and Container Apps ([`infra/terraform`](../infra/terraform/README.md)). The numbers below are list prices times tokens measured on the offline graph. They are not a bill from either cloud. Wall-clock time is not in the table: the two paths execute the same code, so a local sample only shows machine noise. `python aws-it-desk-agent/run.py compare --latency` prints one sample. Live latency needs a Bedrock model and an Azure OpenAI deployment, which this repo does not have.

On the measured token mix, Claude 3.5 Haiku costs more per thousand questions than gpt-4o-mini. Llama 3.1 8B is close to gpt-4o-mini. AgentCore v1 and Container Apps are in the same range under the stated "2 seconds of CPU" assumption. Fargate left running all month is the expensive shape; this stack's `desired_count` default is 0.

<!-- output: python aws-it-desk-agent/run.py compare -->
```text
IT desk playbook agent: list-price cost for 1000 questions/month (not a live bill).
Tokens are the mean of the offline demo questions, counted with policy_qa.text.estimate_tokens (~4 characters per token) on every mock model call.
The Azure and Bedrock paths run this same graph. Only the price card changes.

Mean input tokens per question: 390.0
Mean output tokens per question: 36.6
Mean model calls per question: 3.8

Model USD per 1000 questions (mean tokens x list price):
model | input USD/1M | output USD/1M | USD
azure-openai-gpt-4o-mini | 0.15 | 0.6 | 0.0805
bedrock-claude-3-5-haiku | 0.8 | 4.0 | 0.4584
bedrock-llama-3-1-8b | 0.22 | 0.22 | 0.0939

Runtime USD for the same month. Assumptions, not measurements: 2s active CPU and 8s session memory at 0.5 GB per question. Fargate is 0.25 vCPU and 0.5 GB.
runtime | USD | note
azure-container-apps | 0.0600 | consumption, per question, scale to zero
bedrock-agentcore-v1 | 0.0602 | microVM v1, CPU only while active, memory for the session
ecs-fargate-always-on | 9.0100 | 730 hours, task left running
ecs-fargate-desired-0 | 0.0000 | this stack's default desired_count

Sources: azure-openai-gpt-4o-mini: Azure OpenAI gpt-4o-mini list price, the same rate as shared.observability.DEFAULT_PRICE ($0.00015 / $0.0006 per 1K tokens) and .env.example. The Azure IaC default deployment name is gpt-5-mini; this table does not guess that price. bedrock-claude-3-5-haiku: Amazon Bedrock on-demand pricing for Claude 3.5 Haiku. bedrock-llama-3-1-8b: Amazon Bedrock on-demand pricing for Llama 3.1 8B Instruct.
AgentCore rates: AWS AgentCore pricing page, Runtime microVM v1 ($0.0895 per vCPU-hour, $0.00945 per GB-hour).
Container Apps rates: $0.000024 per vCPU-second and $0.000003 per GiB-second.
Fargate rates: Linux/x86 us-east-1, $0.04048 per vCPU-hour and $0.004445 per GB-hour.
CloudWatch holds the log group (365-day retention). Ingestion is not priced; no live traffic was sent. Azure Monitor would hold the same stdout lines.
```
<!-- /output -->

## Run

```bash
python aws-it-desk-agent/run.py
python aws-it-desk-agent/run.py "How do I reset a forgotten password?"
python aws-it-desk-agent/run.py compare
uvicorn it_desk.service:create_app --factory --port 8080   # PYTHONPATH=aws-it-desk-agent:projects/01-policy-qa-rag:.
curl -s localhost:8080/ping
curl -s -X POST localhost:8080/invocations -H 'content-type: application/json' \
  -d '{"question":"How do I reset a forgotten password?"}'
```

`GET /ping` and `POST /invocations` are the AgentCore Runtime contract. `POST /ask` is the same handler.

## Layout

| File | What it does |
|---|---|
| [`Dockerfile`](Dockerfile) | Image for AgentCore (arm64) or Fargate. Mock model unless the env says otherwise. |
| [`it_desk/`](it_desk/README.md) | Playbooks, Bedrock client, CloudWatch sink, HTTP service, cost comparison. |
| [`terraform/`](terraform/README.md) | AgentCore or Fargate, ECR, IAM, KMS, CloudWatch. Offline `terraform test`. |
| [`tests/`](tests/README.md) | Offline tests for the graph, Bedrock bodies, HTTP, logs and the cost table. |
| [`run.py`](run.py) | CLI. `compare` prints the cost table. |

## Live environment

| Variable | Role |
|---|---|
| `IT_DESK_PROVIDER` | `mock` (default) or `bedrock` |
| `BEDROCK_MODEL_ID` | Claude or Llama model id. Default Claude 3.5 Haiku |
| `AWS_REGION` | Bedrock and CloudWatch region. Default `us-east-1` |
| `IT_DESK_LOG_MODE` | `cloudwatch` calls `PutLogEvents`. Anything else keeps an in-memory sink and stdout |
| `IT_DESK_LOG_GROUP` | CloudWatch log group. The stack creates `/it-desk/playbook` |
| `IT_DESK_LOG_STREAM` | Stream name. Default `it-desk-playbook` |

Install the client with `uv sync --extra aws` (`boto3`). The mock path does not import it.
