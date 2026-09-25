"""Tiny text utilities: tokenization, crude stemming, stopwords (no dependencies)."""

from __future__ import annotations

import re

_STOPWORDS = """a an and are as at be by can do does for from how i if in into is it its may me my
of on or our per should so than that the their them there these they this to up us was we what
when where which who why will with you your any all must not"""
STOPWORDS = frozenset(_STOPWORDS.split())


def stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> list[str]:
    """Lowercased, stemmed content words."""
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]


def estimate_tokens(text: str) -> int:
    """~4 characters per token: good enough for budgeting without a tokenizer dependency."""
    return max(1, (len(text) + 3) // 4)
