"""Memory types, the key catalogue, TTLs and the write-policy tables.

Three kinds of long-term memory, each in its own Store namespace
``("memory", <user_id>, <kind>)``:

* **semantic** (``profile``): facts about the customer - home city, employer, savings goal.
* **episodic** (``episode``): short summaries of past conversations ("asked about wire
  transfer limits"), so the assistant can pick up where it left off.
* **procedural** (``preference``): how the customer wants to be served - name to use,
  contact channel, language, answer length. Procedural memory is limited to an allowlist of
  presentation keys: a customer can change *how* the assistant talks, never *what policy*
  it applies (fees, limits, verification).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["profile", "episode", "preference"]
Source = Literal["user_stated", "inferred", "summary"]
KINDS: tuple[str, ...] = ("profile", "episode", "preference")

DAY = 86_400.0
TTL_SECONDS: dict[str, float | None] = {
    "profile": 365 * DAY,  # re-confirm yearly
    "episode": 90 * DAY,  # conversation summaries age out
    "preference": None,  # until changed or forgotten
}
HALF_LIFE_DAYS: dict[str, float] = {"profile": 180.0, "episode": 30.0, "preference": 365.0}
MIN_CONFIDENCE = 0.6

# Descriptions are embedded with the value so retrieval can match the question's wording
# ("where do I live" -> home_city). A production build would use a real embedding model.
KEYS: dict[str, tuple[str, str]] = {
    "home_city": ("profile", "home city where I live, my address location, moved"),
    "employer": ("profile", "employer where I work, my job, company"),
    "savings_goal": ("profile", "savings goal, what I am saving for"),
    "note": ("profile", "something I asked you to remember"),
    "name_to_use": ("preference", "my name, what to call me"),
    "contact_channel": ("preference", "how to contact me, contact channel, reach me"),
    "language": ("preference", "language to reply in"),
    "answer_style": ("preference", "answer length and tone, short or detailed"),
}
PREFERENCE_ALLOWLIST = frozenset(k for k, (kind, _) in KEYS.items() if kind == "preference")


class HistoryItem(BaseModel):
    value: str
    source: Source
    replaced_at: float


class MemoryRecord(BaseModel):
    """What is stored as the Store item value (plus ``text``, the indexed field)."""

    kind: Kind
    key: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: Source
    created_at: float
    updated_at: float
    expires_at: float | None = None
    history: list[HistoryItem] = Field(default_factory=list)
    text: str = ""

    @property
    def mem_id(self) -> str:
        return f"mem:{self.key}"


class Candidate(BaseModel):
    """A memory the extractor proposes; the write policy decides what happens to it."""

    kind: Kind
    key: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: Source = "user_stated"
