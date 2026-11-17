"""Cost comparison of the IT desk agent on Azure versus Amazon Bedrock.

Token counts are measured by running the offline graph (the same code both clouds host).
Dollars are list prices from ``pricing.py``. Wall-clock time is omitted from the default
report because it changes from machine to machine; ``--latency`` prints one local sample.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult

from it_desk.agent import build_agent
from it_desk.playbook import DEMO_QUESTIONS
from it_desk.pricing import MODELS, REQUESTS, model_cost, runtime_costs
from policy_qa.text import estimate_tokens
from shared.llm import MockChatModel


class MeteredMock(MockChatModel):
    """Mock model that counts the characters the graph actually sends and receives."""

    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        self.tokens_in += sum(estimate_tokens(str(m.content)) for m in messages)
        self.calls += 1
        result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        self.tokens_out += estimate_tokens(str(result.generations[0].message.content))
        return result


@dataclass(frozen=True)
class Sample:
    question: str
    status: str
    tokens_in: int
    tokens_out: int
    calls: int
    latency_ms: int


def measure(question: str) -> Sample:
    meter = MeteredMock(responder=MockChatModel().responder)
    # The portfolio mock responder is what project 01 uses. Re-bind the IT desk one.
    from policy_qa.llm import mock_responder

    meter.responder = mock_responder
    started = time.perf_counter()
    state = build_agent(meter).invoke({"question": question})
    elapsed = int((time.perf_counter() - started) * 1000)
    return Sample(
        question=question,
        status=state["final"]["status"],
        tokens_in=meter.tokens_in,
        tokens_out=meter.tokens_out,
        calls=meter.calls,
        latency_ms=elapsed,
    )


def samples() -> list[Sample]:
    return [measure(q) for q in DEMO_QUESTIONS]


def _money(value: float) -> str:
    return f"{value:.4f}"


def report(rows: list[Sample] | None = None, *, latency: bool = False) -> str:
    rows = rows if rows is not None else samples()
    mean_in = sum(r.tokens_in for r in rows) / len(rows)
    mean_out = sum(r.tokens_out for r in rows) / len(rows)
    lines = [
        "IT desk playbook agent: list-price cost for "
        f"{REQUESTS} questions/month (not a live bill).",
        "Tokens are the mean of the offline demo questions, counted with "
        "policy_qa.text.estimate_tokens (~4 characters per token) on every mock model call.",
        "The Azure and Bedrock paths run this same graph. Only the price card changes.",
        "",
        f"Mean input tokens per question: {mean_in:.1f}",
        f"Mean output tokens per question: {mean_out:.1f}",
        f"Mean model calls per question: {sum(r.calls for r in rows) / len(rows):.1f}",
        "",
        f"Model USD per {REQUESTS} questions (mean tokens x list price):",
        "model | input USD/1M | output USD/1M | USD",
    ]
    for name, row in MODELS.items():
        cost = model_cost(name, mean_in, mean_out)
        lines.append(
            f"{name} | {row['input_per_million']} | {row['output_per_million']} | {_money(cost)}"
        )
    lines += [
        "",
        "Runtime USD for the same month. Assumptions, not measurements: "
        "2s active CPU and 8s session memory at 0.5 GB per question. "
        "Fargate is 0.25 vCPU and 0.5 GB.",
        "runtime | USD | note",
    ]
    notes = {
        "azure-container-apps": "consumption, per question, scale to zero",
        "bedrock-agentcore-v1": "microVM v1, CPU only while active, memory for the session",
        "ecs-fargate-always-on": "730 hours, task left running",
        "ecs-fargate-desired-0": "this stack's default desired_count",
    }
    for name, cost in runtime_costs().items():
        lines.append(f"{name} | {_money(cost)} | {notes[name]}")
    lines += [
        "",
        "Sources: " + " ".join(f"{name}: {row['source']}" for name, row in MODELS.items()),
        "AgentCore rates: AWS AgentCore pricing page, Runtime microVM v1 "
        "($0.0895 per vCPU-hour, $0.00945 per GB-hour).",
        "Container Apps rates: $0.000024 per vCPU-second and $0.000003 per GiB-second.",
        "Fargate rates: Linux/x86 us-east-1, $0.04048 per vCPU-hour and $0.004445 per GB-hour.",
        "CloudWatch holds the log group (365-day retention). Ingestion is not priced; "
        "no live traffic was sent. Azure Monitor would hold the same stdout lines.",
    ]
    if latency:
        lines.append("")
        lines.append("Local mock latency (one sample, not a gate):")
        for row in rows:
            lines.append(f"{row.latency_ms} ms | {row.status} | {row.question}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the IT desk cost comparison")
    parser.add_argument(
        "--latency",
        action="store_true",
        help="append one local latency sample (varies by machine)",
    )
    args = parser.parse_args(argv)
    print(report(latency=args.latency))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
