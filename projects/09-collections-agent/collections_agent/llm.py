"""Plan-proposal and message-drafting prompts with deterministic offline mocks."""

from __future__ import annotations

import json
from collections.abc import Sequence

from langchain_core.messages import BaseMessage

from collections_agent.policy import DISCLOSURE

PROPOSE_SYSTEM = (
    "TASK: PROPOSE_PLAN\nYou are a collections negotiator. Given the (masked) account summary, "
    'propose an affordable payment plan as JSON: {"months": int, "discount_pct": number, '
    '"rationale": str}. Company limits are provided; stay within them.'
)
DRAFT_SYSTEM = (
    "TASK: DRAFT_MESSAGE\nWrite a short, respectful message offering the approved payment plan. "
    "Never threaten, never mention legal action, arrest, credit damage or third parties. End "
    f"with exactly this disclosure: '{DISCLOSURE}'. Reply with the message body only."
)


def mock_responder(messages: Sequence[BaseMessage]) -> str:
    system, user = str(messages[0].content), str(messages[-1].content)
    payload = json.loads(user)
    if system.startswith("TASK: PROPOSE_PLAN"):
        bal = payload["balance"]
        months = 6 if bal <= 1500 else 12
        return json.dumps(
            {
                "months": months,
                "discount_pct": 0,
                "rationale": f"{months} months keeps installments affordable",
            }
        )
    if system.startswith("TASK: DRAFT_MESSAGE"):
        p = payload["plan"]
        return (
            f"Hello {payload['first_name']},\n\nThanks for being a customer. To make things "
            f"easier, we can set up {p['months']} monthly payments of "
            f"${p['installment']:.2f} (total ${p['total']:.2f}). Just reply 'YES' to confirm, "
            f"or let us know what works better for you.\n\n{DISCLOSURE}"
        )
    return "{}"
