"""Banking assistant with short-term (checkpointer) and long-term (Store) memory.

intake --chat--> recall -> respond -> remember -> END
       --forget / forget everything--> forget -> END
       --consent on / off--> consent -> END

* **Short-term**: the thread's messages live in the checkpointer (``thread_id``).
* **Long-term**: semantic / episodic / procedural memories live in the LangGraph Store under
  ``("memory", user_id, kind)``. ``user_id`` comes from the authenticated run config, never
  from message text, so "I am alice" from bob reads bob's namespace.
* ``recall`` loads preferences plus the top memories by relevance x recency x confidence.
* ``respond`` answers from those memories only; a guard strips any ``[mem:<key>]`` citation
  that was not in the prompt (a hallucinated memory) and records a degrade exit.
* ``remember`` runs the extractor and applies the write policy (consent, poisoning,
  allowlist, credentials, redaction, confidence, conflicts). Poisoning attempts escalate.
* ``forget`` deletes one key or everything (store + every checkpointed thread of the user),
  leaving a content-free audit tombstone. Withdrawing consent also erases memories.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages
from langgraph.store.base import BaseStore
from pydantic import ValidationError

from memory_agent import llm as prompts
from memory_agent.memory import Clock, MemoryStore, MemoryUnavailableError, make_store
from memory_agent.policy import POLICY_OVERRIDE, decide
from memory_agent.schema import Candidate
from shared.context import looks_like_injection
from shared.observability import install
from shared.resilience import ModelUnavailableError, exit_record, with_fallback

REFUSED_NOTE = (
    "I didn't save that: I can't keep instructions that change how your account is "
    "handled, and the request has been passed to our security team."
)
TURN = "__turn__"  # reducer marker: start a fresh per-turn list
CITE = re.compile(r"\[mem:([\w:.-]+)\]")
FORGET_ALL = re.compile(
    r"\b(?:forget everything|forget all about me|delete (?:all )?my (?:data|memories)|"
    r"right to be forgotten)\b",
    re.I,
)
FORGET_KEY = re.compile(r"\bforget (?:my|where i|what i|that i|about my)\s+(\w+)", re.I)
FORGET_WORDS = {
    "city": "home_city",
    "live": "home_city",
    "address": "home_city",
    "employer": "employer",
    "work": "employer",
    "job": "employer",
    "name": "name_to_use",
    "contact": "contact_channel",
    "saving": "savings_goal",
    "savings": "savings_goal",
    "language": "language",
}
CONSENT_OFF = re.compile(r"\b(?:stop remembering|don'?t remember|do not remember|opt out)\b", re.I)
CONSENT_ON = re.compile(r"\b(?:you can remember|remember things about me|opt in)\b", re.I)


def per_turn(old: list | None, new: list | None) -> list:
    new = new or []
    if new and new[0] == TURN:
        return list(new[1:])
    return [*(old or []), *new]


class ChatState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    intent: str
    forget_key: str | None
    recalled: list[dict[str, Any]]
    answer: str
    decisions: list[dict[str, str]]
    trace: Annotated[list[str], per_turn]
    exits: Annotated[list[dict[str, str]], per_turn]


def _user(config: RunnableConfig) -> str:
    return str(config["configurable"]["user_id"])


def build_graph(
    llm: BaseChatModel | None = None,
    store: BaseStore | None = None,
    checkpointer: Any = None,
    clock: Clock = time.time,
):
    install()
    if llm is None:
        from shared.llm import get_llm

        llm = get_llm(mock_responder=prompts.mock_responder)
    llm = with_fallback(llm)
    store = store if store is not None else make_store()
    checkpointer = checkpointer if checkpointer is not None else InMemorySaver()
    mem = MemoryStore(store, clock)

    def consent_for(user: str, config: RunnableConfig) -> bool:
        return mem.consent(user, bool(config["configurable"].get("memory_consent", False)))

    def intake(state: ChatState, config: RunnableConfig) -> dict[str, Any]:
        text = str(state["messages"][-1].content)
        user, thread = _user(config), str(config["configurable"]["thread_id"])
        store.put(("threads", user), thread, {"at": clock()})  # for right-to-be-forgotten
        key = None
        if FORGET_ALL.search(text):
            intent = "forget_all"
        elif m := FORGET_KEY.search(text):
            intent, key = "forget", FORGET_WORDS.get(m.group(1).lower())
        elif CONSENT_OFF.search(text):
            intent = "consent_off"
        elif CONSENT_ON.search(text):
            intent = "consent_on"
        else:
            intent = "chat"
        return {
            "intent": intent,
            "forget_key": key,
            "recalled": [],
            "decisions": [],
            "trace": [TURN, "intake"],
            "exits": [TURN],
        }

    def recall(state: ChatState, config: RunnableConfig) -> dict[str, Any]:
        user = _user(config)
        query = str(state["messages"][-1].content)
        try:
            if not consent_for(user, config):
                return {"recalled": [], "trace": ["recall"]}
            recs = mem.preferences(user)  # procedural memory applies to every turn
            if prompts.BROAD.search(query):  # "what do you know about me": everything
                recs += [r for r in mem.all(user) if r.kind != "preference"]
                scores = [1.0] * len(recs)
            else:
                hits = mem.search(user, query)
                scores = [1.0] * len(recs) + [h.score for h in hits]
                recs += [h.record for h in hits]
        except MemoryUnavailableError:
            down = exit_record("recall", "degrade", "memory store down: answering without memory")
            return {"recalled": [], "trace": ["recall"], "exits": [down]}
        recalled, exits = [], []
        for r, sc in zip(recs, scores, strict=True):
            if looks_like_injection(r.value) or POLICY_OVERRIDE.search(r.value):
                # defence in depth: a poisoned record that predates the policy never
                # reaches the prompt
                exits.append(exit_record("recall", "escalate", f"quarantined {r.mem_id}"))
                continue
            recalled.append({"id": r.mem_id, "kind": r.kind, "value": r.value, "score": sc})
        return {"recalled": recalled, "trace": ["recall"], "exits": exits}

    def respond(state: ChatState, config: RunnableConfig) -> dict[str, Any]:
        recalled = state.get("recalled", [])
        block = "\n".join(f"[{r['id']}] ({r['kind']}) {r['value']}" for r in recalled)
        system = prompts.ANSWER_SYSTEM + "MEMORY:\n" + (block or "(none)")
        history = [m for m in state["messages"] if isinstance(m, HumanMessage | AIMessage)][-7:]
        exits = []
        try:
            raw = str(llm.invoke([SystemMessage(system), *history]).content)
        except ModelUnavailableError:
            raw = "I'm having trouble answering right now. Nothing about you was changed."
            exits.append(exit_record("respond", "degrade", "model unavailable: holding reply"))
        allowed = {r["id"].removeprefix("mem:") for r in recalled}
        kept, dropped = [], 0
        for sentence in re.split(r"(?<=[.!?])\s+", raw):
            if set(CITE.findall(sentence)) - allowed:
                dropped += 1
                continue
            kept.append(sentence)
        answer = " ".join(kept) or prompts.NOT_ON_FILE
        if dropped:
            exits.append(
                exit_record("respond", "degrade", f"{dropped} unsupported memory claim(s)")
            )
        display = CITE.sub("", answer).replace(" .", ".").replace("  ", " ").strip()
        return {
            "answer": answer,
            "messages": [AIMessage(display)],
            "trace": ["respond"],
            "exits": exits,
        }

    def remember(state: ChatState, config: RunnableConfig) -> dict[str, Any]:
        user = _user(config)
        text = str(state["messages"][-2].content)  # the customer's message this turn
        try:
            consent = consent_for(user, config)
        except MemoryUnavailableError:
            return {
                "trace": ["remember"],
                "exits": [exit_record("remember", "degrade", "memory store down: not saved")],
            }
        if not consent:
            return {
                "decisions": [{"key": "*", "action": "skip", "reason": "no memory consent"}],
                "trace": ["remember"],
            }
        try:
            raw = str(
                llm.invoke([SystemMessage(prompts.EXTRACT_SYSTEM), HumanMessage(text)]).content
            )
            proposed = json.loads(raw)
        except ModelUnavailableError:
            return {
                "trace": ["remember"],
                "exits": [exit_record("remember", "degrade", "extractor down: nothing saved")],
            }
        except json.JSONDecodeError:
            proposed = []
        decisions, exits = [], []
        for obj in proposed if isinstance(proposed, list) else []:
            try:
                cand = Candidate(**obj)
            except (ValidationError, TypeError):
                decisions.append({"key": str(obj)[:40], "action": "reject", "reason": "malformed"})
                continue
            try:
                existing = mem.get(user, cand.kind, cand.key)
                d = decide(cand, existing, consent)
                if d.action in ("save", "update"):
                    c = d.candidate
                    mem.upsert(user, c.kind, c.key, c.value, c.confidence, c.source)
            except MemoryUnavailableError:
                exits.append(exit_record("remember", "degrade", "memory store down: not saved"))
                break
            decisions.append({"key": cand.key, "action": d.action, "reason": d.reason})
            if d.flagged:
                store.put(
                    ("audit", user),
                    f"flag-{int(clock() * 1000)}-{uuid.uuid4().hex[:8]}",
                    {"flag": "memory_poisoning", "key": cand.key, "reason": d.reason},
                )
                exits.append(exit_record("remember", "escalate", f"flagged: {d.reason}"))
        out: dict[str, Any] = {"decisions": decisions, "trace": ["remember"], "exits": exits}
        if any(e["exit"] == "escalate" for e in exits):
            last = state["messages"][-1]  # this turn's reply: amend it in place (same id)
            kept = str(last.content).replace(prompts.ACK, "").strip()
            out["messages"] = [AIMessage(f"{kept} {REFUSED_NOTE}".strip(), id=last.id)]
        return out

    def forget(state: ChatState, config: RunnableConfig) -> dict[str, Any]:
        user, thread = _user(config), str(config["configurable"]["thread_id"])
        out: dict[str, Any] = {"trace": ["forget"]}
        try:
            if state["intent"] == "forget_all":
                n = erase_user(user, keep_thread=thread)
                msg = f"Done. I erased everything I remembered about you ({n} item(s))."
                out["messages"] = [RemoveMessage(id=REMOVE_ALL_MESSAGES), AIMessage(msg)]
            elif state.get("forget_key"):
                n = mem.forget(user, state["forget_key"])
                msg = f"Done. I no longer remember your {state['forget_key'].replace('_', ' ')}."
                out["messages"] = [AIMessage(msg if n else "I didn't have that on file.")]
            else:
                out["messages"] = [AIMessage("Which detail would you like me to forget?")]
        except MemoryUnavailableError:
            out["messages"] = [
                AIMessage(
                    "I can't reach my memory right now; your request is "
                    "logged and will be completed."
                )
            ]
            out["exits"] = [exit_record("forget", "escalate", "erasure queued for an operator")]
        out["answer"] = str(out["messages"][-1].content)
        return out

    def consent(state: ChatState, config: RunnableConfig) -> dict[str, Any]:
        user = _user(config)
        granted = state["intent"] == "consent_on"
        try:
            mem.set_consent(user, granted)
            n = 0 if granted else mem.forget(user)
        except MemoryUnavailableError:
            msg = "I can't update your memory setting right now; please try again shortly."
            return {
                "messages": [AIMessage(msg)],
                "answer": msg,
                "trace": ["consent"],
                "exits": [exit_record("consent", "escalate", "consent change not applied")],
            }
        msg = (
            "OK, I'll remember your preferences from now on."
            if granted
            else f"OK, I won't remember anything about you, and I erased {n} saved item(s)."
        )
        return {"messages": [AIMessage(msg)], "answer": msg, "trace": ["consent"]}

    def erase_user(user: str, keep_thread: str | None = None) -> int:
        """Right to be forgotten: memories, consent, and every checkpointed thread."""
        n = mem.forget(user)
        store.delete(("consent", user), "memory")
        for item in store.search(("threads", user), limit=10_000):
            if item.key != keep_thread:
                checkpointer.delete_thread(item.key)
            store.delete(("threads", user), item.key)
        return n

    def after_intake(state: ChatState) -> str:
        return {
            "forget": "forget",
            "forget_all": "forget",
            "consent_on": "consent",
            "consent_off": "consent",
        }.get(state["intent"], "recall")

    g = StateGraph(ChatState)
    for name, fn in [
        ("intake", intake),
        ("recall", recall),
        ("respond", respond),
        ("remember", remember),
        ("forget", forget),
        ("consent", consent),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", after_intake, ["recall", "forget", "consent"])
    g.add_edge("recall", "respond")
    g.add_edge("respond", "remember")
    g.add_edge("remember", END)
    g.add_edge("forget", END)
    g.add_edge("consent", END)
    compiled = g.compile(checkpointer=checkpointer, store=store, name="memory-agent")
    compiled.memory, compiled.erase_user, compiled.checkpointer_ = mem, erase_user, checkpointer
    return compiled


class MemoryAgent:
    """Small facade: one graph, many users and sessions."""

    def __init__(self, **kwargs: Any):
        self.graph = build_graph(**kwargs)
        self.memory: MemoryStore = self.graph.memory

    def chat(self, user_id: str, thread_id: str, text: str, consent: bool = True) -> dict:
        cfg = {
            "configurable": {"user_id": user_id, "thread_id": thread_id, "memory_consent": consent}
        }
        return self.graph.invoke({"messages": [HumanMessage(text)]}, cfg)

    def forget_user(self, user_id: str) -> int:
        return self.graph.erase_user(user_id)
