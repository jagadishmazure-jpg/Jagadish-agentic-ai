"""Journey agent over the governed mesh: parallel A2A fan-out, one trace, idempotent writes."""

from control_plane.journey import regex_parse
from shared.observability import telemetry

ACME = "Can we promise {q} units of SKU-200 to ACME-B2B within 4 weeks?"


def test_promise(ask):
    r = ask(ACME.format(q=300))
    assert r["decision"]["status"] == "promise" and r["decision"]["atp"] == 360
    assert "360" in r["answer"] and r.get("po") is None
    assert sorted(r["trace"][2:5]) == ["crm", "demand", "sap"]


def test_shortfall_drafts_rounded_po_once(ask, net):
    r = ask(ACME.format(q=500), thread="same")
    assert r["po"]["qty"] == 150 and len(net.services.erp.drafts) == 1
    ask(ACME.format(q=500), thread="same")  # replay: same idempotency key
    assert len(net.services.erp.drafts) == 1


def test_one_trace_across_all_a2a_calls(ask, net):
    ask(ACME.format(q=300))
    trace_ids = {a["traceparent"].split("-")[1] for a in net.cp.audit}
    assert len(net.cp.audit) == 3 and len(trace_ids) == 1
    tid = int(trace_ids.pop(), 16)
    server_spans = [s for s in telemetry().spans("a2a.server") if s.context.trace_id == tid]
    assert len(server_spans) == 3  # the peers continued the caller's trace


def test_tenant_propagates_to_peers(ask, net):
    ask("Can we promise 100 units of SKU-200 to INITECH-B2B within 4 weeks?", tenant="contoso")
    assert {a["tenant"] for a in net.cp.audit} == {"contoso"}


def test_credit_hold_never_promises(ask):
    r = ask("Can we promise 1 units of SKU-200 to GLOBEX-B2B within 4 weeks?")
    assert r["decision"]["status"] == "unknown" and "credit hold" in r["answer"]


def test_killed_peer_skipped_by_discovery(ask, net):
    net.cp.registry.kill("demand-agent", "drift")
    r = ask(ACME.format(q=300))
    assert "demand" not in r["trace"]
    assert r["decision"]["status"] == "unknown"
    assert not any(a["callee"] == "demand-agent" for a in net.cp.audit)


def test_regex_parse():
    a = regex_parse("promise 40 units of SKU-300 to ACME-B2B within 3 weeks")
    assert (a.qty, a.sku, a.customer_id, a.weeks) == (40, "SKU-300", "ACME-B2B", 3)
    assert regex_parse("hello") is None
