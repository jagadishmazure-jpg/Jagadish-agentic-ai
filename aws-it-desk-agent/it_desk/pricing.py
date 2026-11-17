"""List prices for the cost comparison. These are published rates, not a live bill.

Nothing in CI calls Bedrock or Azure OpenAI. Token counts come from the offline graph;
dollars are those counts times the rates below. Re-check the vendor pages before a
procurement decision. Rates were taken from the public price pages on 2026-11-17.
"""

from __future__ import annotations

# USD per 1,000,000 tokens.
MODELS: dict[str, dict[str, float | str]] = {
    "azure-openai-gpt-4o-mini": {
        "input_per_million": 0.15,
        "output_per_million": 0.60,
        "source": (
            "Azure OpenAI gpt-4o-mini list price, the same rate as "
            "shared.observability.DEFAULT_PRICE ($0.00015 / $0.0006 per 1K tokens) and "
            ".env.example. The Azure IaC default deployment name is gpt-5-mini; this table "
            "does not guess that price."
        ),
    },
    "bedrock-claude-3-5-haiku": {
        "input_per_million": 0.80,
        "output_per_million": 4.00,
        "model_id": "anthropic.claude-3-5-haiku-20241022-v1:0",
        "source": "Amazon Bedrock on-demand pricing for Claude 3.5 Haiku.",
    },
    "bedrock-llama-3-1-8b": {
        "input_per_million": 0.22,
        "output_per_million": 0.22,
        "model_id": "meta.llama3-1-8b-instruct-v1:0",
        "source": "Amazon Bedrock on-demand pricing for Llama 3.1 8B Instruct.",
    },
}

# Compute list prices, USD.
# Azure Container Apps consumption: $0.000024 per vCPU-second, $0.000003 per GiB-second.
ACA_VCPU_HOUR = 0.000024 * 3600
ACA_GB_HOUR = 0.000003 * 3600
# AgentCore Runtime microVM v1, from https://aws.amazon.com/bedrock/agentcore/pricing/
AGENTCORE_VCPU_HOUR = 0.0895
AGENTCORE_GB_HOUR = 0.00945
# ECS Fargate Linux/x86 in us-east-1 (public Fargate pricing page, long-standing rates).
FARGATE_VCPU_HOUR = 0.04048
FARGATE_GB_HOUR = 0.004445

# Stated assumptions for a month of the same questions. Not measured on AWS or Azure.
REQUESTS = 1000
ACTIVE_CPU_SECONDS = 2.0  # time the process is on CPU, per question
SESSION_SECONDS = 8.0  # session length billed for memory (includes model wait)
MEMORY_GB = 0.5
FARGATE_VCPU = 0.25
FARGATE_HOURS = 730  # a task left running all month; this stack's desired_count default is 0


def model_cost(name: str, tokens_in: float, tokens_out: float, requests: int = REQUESTS) -> float:
    row = MODELS[name]
    per = tokens_in / 1_000_000 * float(row["input_per_million"]) + tokens_out / 1_000_000 * float(
        row["output_per_million"]
    )
    return per * requests


def runtime_costs() -> dict[str, float]:
    """USD for REQUESTS questions under the assumptions above, plus an always-on Fargate month."""
    aca = REQUESTS * (
        ACTIVE_CPU_SECONDS / 3600 * ACA_VCPU_HOUR + SESSION_SECONDS / 3600 * MEMORY_GB * ACA_GB_HOUR
    )
    agentcore = REQUESTS * (
        ACTIVE_CPU_SECONDS / 3600 * AGENTCORE_VCPU_HOUR
        + SESSION_SECONDS / 3600 * MEMORY_GB * AGENTCORE_GB_HOUR
    )
    fargate_month = FARGATE_HOURS * (FARGATE_VCPU * FARGATE_VCPU_HOUR + MEMORY_GB * FARGATE_GB_HOUR)
    return {
        "azure-container-apps": aca,
        "bedrock-agentcore-v1": agentcore,
        "ecs-fargate-always-on": fargate_month,
        "ecs-fargate-desired-0": 0.0,
    }
