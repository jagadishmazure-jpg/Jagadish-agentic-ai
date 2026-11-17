"""The cost table is a pure function of the offline token counts and the price card."""

from it_desk.compare import report, samples
from it_desk.pricing import MODELS, model_cost, runtime_costs


def test_report_is_stable_and_prices_every_model():
    rows = samples()
    text = report(rows)
    assert "not a live bill" in text
    for name in MODELS:
        assert name in text
    again = report(rows)
    assert text == again
    assert " ms |" not in text  # latency is opt-in and not part of the checked report


def test_latency_sample_is_optional():
    rows = samples()
    text = report(rows, latency=True)
    assert "Local mock latency" in text
    assert all(row.latency_ms >= 0 for row in rows)
    assert any(row.status == "answered" for row in rows)
    assert any(row.status == "insufficient_evidence" for row in rows)


def test_claude_costs_more_than_the_azure_small_model_on_this_mix():
    rows = samples()
    mean_in = sum(r.tokens_in for r in rows) / len(rows)
    mean_out = sum(r.tokens_out for r in rows) / len(rows)
    azure = model_cost("azure-openai-gpt-4o-mini", mean_in, mean_out)
    claude = model_cost("bedrock-claude-3-5-haiku", mean_in, mean_out)
    llama = model_cost("bedrock-llama-3-1-8b", mean_in, mean_out)
    assert claude > azure
    assert llama < claude
    costs = runtime_costs()
    assert costs["ecs-fargate-desired-0"] == 0.0
    assert (
        costs["ecs-fargate-always-on"]
        > costs["bedrock-agentcore-v1"]
        > costs["azure-container-apps"]
    )


def test_terraform_names_bedrock_cloudwatch_and_both_runtimes():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "terraform"
    text = "\n".join(p.read_text() for p in root.glob("*.tf"))
    assert 'resource "aws_bedrockagentcore_agent_runtime"' in text
    assert 'resource "aws_ecs_service"' in text
    assert 'resource "aws_cloudwatch_log_group"' in text
    assert "bedrock:InvokeModel" in text
    assert "awslogs" in text
    assert "IT_DESK_PROVIDER" in text
    assert "desired_count" in text
