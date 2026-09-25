"""Retrieval, critic rules and compliance rules (pure functions)."""

from __future__ import annotations

import re

from rfp_agent.knowledge import KB

STOP = set(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "does",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "our",
        "the",
        "to",
        "we",
        "what",
        "which",
        "with",
        "you",
        "your",
        "describe",
        "offer",
    ]
)
# facets the critic requires an answer to cover when the question mentions them
FACETS = {
    "at rest": ("at rest",),
    "in transit": ("in transit",),
    "sso": ("sso",),
    "scim": ("scim",),
    "soc 2": ("soc 2",),
    "iso 27001": ("iso 27001",),
    "gdpr": ("gdpr",),
    "uptime": ("uptime",),
    "rpo": ("rpo",),
    "rto": ("rto",),
    "backup": ("backup",),
}
BANNED_CLAIMS = [
    r"never been breached",
    r"guarantee[sd]? 100%",
    r"unlimited liability",
    r"military[- ]grade",
    r"unhackable",
    r"best in the world",
]
EXPORT_CONTROL = [
    r"\bITAR\b",
    r"\bEAR\b",
    r"\b5D992\b",
    r"\bembargo",
    r"\bIran\b",
    r"\bNorth Korea\b",
    r"\bdual[- ]use\b",
]
CITE_RE = re.compile(r"\[(KB-[A-Z]+-\d{3})\]")
MAX_WORDS = 120


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP}


def retrieve(question: str, k: int = 3) -> list[str]:
    q = words(question)
    scored = sorted(
        ((len(q & words(v["title"] + " " + v["text"])), kid) for kid, v in KB.items()), reverse=True
    )
    return [kid for score, kid in scored if score >= 2][:k]


def required_facets(question: str) -> list[str]:
    q = question.lower()
    return [f for f, keys in FACETS.items() if any(k in q for k in keys)]


def critique(question: str, answer: str, retrieved: list[str]) -> list[str]:
    issues = []
    cited = CITE_RE.findall(answer)
    if not cited:
        issues.append("no knowledge-base citation")
    bad = [c for c in cited if c not in retrieved]
    if bad:
        issues.append(f"cites ids not in retrieved KB context: {bad}")
    missing = [f for f in required_facets(question) if f not in answer.lower()]
    if missing:
        issues.append(f"does not address: {missing}")
    if len(answer.split()) > MAX_WORDS:
        issues.append(f"longer than {MAX_WORDS} words")
    return issues


def compliance_scan(text: str) -> tuple[str, list[str], list[str]]:
    """Return (cleaned_text, banned_claims_removed, export_control_hits)."""
    removed = []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = []
    for s in sentences:
        hit = next((p for p in BANNED_CLAIMS if re.search(p, s, re.I)), None)
        if hit:
            removed.append(s.strip())
        else:
            kept.append(s)
    export = sorted({m.group(0) for p in EXPORT_CONTROL for m in re.finditer(p, text)})
    return " ".join(kept).strip(), removed, export
