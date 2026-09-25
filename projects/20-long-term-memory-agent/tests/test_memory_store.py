"""MemoryStore on the LangGraph Store: ranking, TTL, forgetting, namespace isolation."""

import pytest

from memory_agent.eval_suite import FakeClock
from memory_agent.memory import MemoryStore, make_store


@pytest.fixture
def mem():
    return MemoryStore(make_store(), FakeClock())


def test_relevant_memory_outranks_irrelevant(mem):
    mem.upsert("u1", "profile", "home_city", "Denver", 0.9, "user_stated")
    mem.upsert("u1", "profile", "employer", "Contoso Health", 0.9, "user_stated")
    hits = mem.search("u1", "where do I live now?")
    assert hits and hits[0].record.key == "home_city"


def test_recent_episode_outranks_an_older_one_on_the_same_topic(mem):
    mem.upsert("u1", "episode", "episode:a", "asked about wire transfer limits", 0.8, "summary")
    mem.clock.advance(60)
    mem.upsert("u1", "episode", "episode:b", "asked about wire transfer fees", 0.8, "summary")
    hits = mem.search("u1", "what did we talk about last time about wire transfers?")
    assert [h.record.key for h in hits][:2] == ["episode:b", "episode:a"]
    assert hits[0].score > hits[1].score


def test_ttl_hides_expired_items_and_sweep_deletes_them(mem):
    mem.upsert("u1", "episode", "episode:x", "asked about overdraft fees", 0.8, "summary")
    mem.upsert("u1", "preference", "language", "Spanish", 0.9, "user_stated")
    mem.clock.advance(91)  # episodes live 90 days, preferences have no TTL
    assert [r.key for r in mem.all("u1")] == ["language"]
    assert mem.sweep() == 1
    assert mem.store.get(("memory", "u1", "episode"), "episode:x") is None


def test_update_keeps_bounded_history(mem):
    for city in ["Austin", "Denver", "Boise", "Reno", "Tulsa", "Omaha", "Provo"]:
        mem.clock.advance(1)
        rec = mem.upsert("u1", "profile", "home_city", city, 0.9, "user_stated")
    assert rec.value == "Provo" and len(rec.history) == 5
    assert rec.history[-1].value == "Omaha"


def test_forget_leaves_a_content_free_tombstone(mem):
    mem.upsert("u1", "profile", "home_city", "Denver", 0.9, "user_stated")
    mem.upsert("u1", "profile", "employer", "Contoso", 0.9, "user_stated")
    assert mem.forget("u1", "home_city") == 1
    assert [r.key for r in mem.all("u1")] == ["employer"]
    assert mem.forget("u1") == 1 and mem.all("u1") == []
    audit = mem.audit("u1")
    assert [a["scope"] for a in audit] == ["home_city", "all"]
    assert "Denver" not in str(audit) and "Contoso" not in str(audit)


def test_namespaces_are_per_user_and_require_an_identity(mem):
    mem.upsert("alice", "profile", "home_city", "Denver", 0.9, "user_stated")
    assert mem.search("bob", "where does alice live? Denver") == []
    assert mem.all("bob") == []
    for bad in ("", "alice/../bob"):
        with pytest.raises(ValueError):
            mem.all(bad)
