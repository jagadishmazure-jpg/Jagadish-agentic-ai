"""Synthesizer prompt + deterministic mock that writes cited talking points and risks."""

from __future__ import annotations

import json
from collections.abc import Sequence

from langchain_core.messages import BaseMessage

SYNTH_SYSTEM = (
    "TASK: SYNTHESIZE\n"
    "You prepare account executives for customer meetings. From the research JSON, write "
    "3-5 talking points and 1-3 risks. Every bullet MUST end with the source id(s) in "
    "brackets, e.g. [DEAL-1]. Use only facts in the JSON. Reply with JSON: "
    '{"talking_points": ["..."], "risks": ["..."]}'
)


def mock_responder(messages: Sequence[BaseMessage]) -> str:
    data = json.loads(str(messages[-1].content))
    f = data["findings"]
    points, risks = [], []
    deals = f.get("deals", {}).get("items", [])
    if deals:
        top = max(deals, key=lambda d: d["amount"])
        points.append(
            f"Advance {top['name']} (${top['amount']:,}, {top['stage']}), target "
            f"close {top['close']} [{top['id']}]"
        )
    crm = f.get("crm", {}).get("items", [])
    if crm:
        latest = max(crm, key=lambda i: i["date"])
        first = min(crm, key=lambda i: i["date"])
        points.append(
            f"Follow up on last touch ({latest['type']} {latest['date']}): "
            f"{latest['note']} [{latest['id']}]"
        )
        points.append(f"Reinforce exec sponsor value: {first['note']} [{first['id']}]")
        risks += [
            f"Competitive threat: {i['note']} [{i['id']}]"
            for i in crm
            if "competitor" in i["note"].lower()
        ]
    news = f.get("news", {}).get("items", [])
    if news:
        points.append(f"Open with recent news: {news[0]['headline']} [{news[0]['id']}]")
    for t in f.get("support", {}).get("items", []):
        if t["status"] == "open" and t["priority"] in ("P1", "P2"):
            risks.append(
                f"Open {t['priority']} ticket for {t['age_days']} days: "
                f"{t['subject']} - acknowledge and share ETA [{t['id']}]"
            )
    return json.dumps({"talking_points": points[:5], "risks": risks[:3]})


# With every model deployment down, the same deterministic rules produce cited bullets
# (degrade exit) - never uncited free text.
rule_based_synthesis = mock_responder
