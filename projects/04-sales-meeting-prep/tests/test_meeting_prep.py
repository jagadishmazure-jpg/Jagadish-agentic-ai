import json
import time

from meeting_prep.graph import Brief, build_graph
from meeting_prep.llm import mock_responder
from meeting_prep.sources import seed_sources
from shared.llm import MockChatModel


def test_complete_brief_with_cited_sources(prep):
    r = prep()
    brief = Brief.model_validate(r["brief"])
    assert brief.status == "complete" and brief.gaps == []
    assert set(brief.sources_used) == {"crm", "news", "deals", "support"}
    assert all("[" in p for p in brief.talking_points)
    assert "| DEAL-2 | 3-year renewal | $420,000 |" in brief.markdown
    assert any("SUP-1" in risk for risk in brief.risks)


def test_branches_run_in_parallel():
    src = seed_sources(latency_s=0.2)
    graph = build_graph(src)
    t0 = time.perf_counter()
    r = graph.invoke({"account_id": "ACME", "account_name": "Acme Corp"})
    elapsed = time.perf_counter() - t0
    assert len(r["timings"]) == 4
    assert elapsed < 0.6  # 4 x 0.2s sequential would be >= 0.8s


def test_fan_in_synthesizes_once_with_all_findings_merged(prep):
    calls = []

    def spy(msgs):
        calls.append(json.loads(msgs[-1].content))
        return mock_responder(msgs)

    r = prep(llm=MockChatModel(responder=spy))
    assert len(calls) == 1  # join: synthesizer runs once after all branches
    assert set(calls[0]["findings"]) == {"crm", "news", "deals", "support"}
    assert set(r["findings"]) == {"crm", "news", "deals", "support"}  # dict-merge reducer


def test_partial_failure_still_produces_brief_with_gap(prep):
    r = prep(sources=seed_sources(failures={"news": ConnectionError("503")}))
    brief = r["brief"]
    assert brief["status"] == "partial" and brief["gaps"] == ["news"]
    assert "## Gaps" in brief["markdown"] and "news** unavailable" in brief["markdown"]
    assert "NEWS-1" not in brief["markdown"]
    assert r["errors"] and "news" in r["errors"][0]


def test_transient_error_is_retried_once_and_recovers(prep):
    src = seed_sources(transient={"deals": 1})
    r = prep(sources=src)
    assert r["findings"]["deals"]["status"] == "ok" and r["findings"]["deals"]["attempts"] == 2
    assert r["brief"]["status"] == "complete"


def test_non_transient_error_is_not_retried(prep):
    src = seed_sources(failures={"crm": PermissionError("token expired")})
    r = prep(sources=src)
    assert src.calls["crm"] == 1
    assert r["findings"]["crm"]["status"] == "error"
    assert r["brief"]["status"] == "partial"


def test_below_quorum_marks_brief_insufficient(prep):
    fail = {s: ConnectionError("down") for s in ("crm", "news", "deals")}
    r = prep(sources=seed_sources(failures=fail))
    assert r["brief"]["status"] == "insufficient_data"
    assert "Not enough sources" in r["brief"]["markdown"]


def test_uncited_or_invented_bullets_are_dropped(prep):
    def sloppy(_msgs):
        return json.dumps(
            {
                "talking_points": [
                    "Great account, push hard",
                    "Cite fake [DEAL-99]",
                    "Renewal is in negotiation [DEAL-2]",
                ],
                "risks": ["They might churn"],
            }
        )

    r = prep(llm=MockChatModel(responder=sloppy))
    assert r["brief"]["talking_points"] == ["Renewal is in negotiation [DEAL-2]"]
    assert r["brief"]["risks"] == []
    assert r["synthesis"]["dropped_uncited"] == 3


def test_requested_subset_of_sources():
    src = seed_sources()
    r = build_graph(src).invoke(
        {"account_id": "ACME", "account_name": "Acme Corp", "sources": ["crm", "deals"]}
    )
    assert set(src.calls) == {"crm", "deals"}
    assert r["brief"]["status"] == "complete"
