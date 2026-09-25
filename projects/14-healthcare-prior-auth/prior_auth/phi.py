"""PHI redaction for the knowledge plane (text sent to models / packed into context) and for
logs (a logging.Filter that is a safety net even if a developer logs raw values)."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from shared.context import sanitize

MRN = re.compile(r"\bMRN[-: ]?\d{5,}\b", re.I)
DOB = re.compile(r"\b(DOB|date of birth)[:\s]+\d{4}-\d{2}-\d{2}\b", re.I)
MEMBER_ID = re.compile(r"\bM-\d{4}\b")
PHONE = re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")


def redact(text: str, names: Iterable[str] = (), member_ids: bool = False) -> str:
    """Names (from the member record), MRN, DOB, plus the shared SSN/phone/email/card rules."""
    out = sanitize(text, redact_pii=True).text
    out = MRN.sub("[MRN]", out)
    out = PHONE.sub("[PHONE]", out)
    out = DOB.sub(lambda m: f"{m.group(1)}: [DOB]", out)
    for n in names:
        for part in (n, *n.split()):
            if len(part) > 2:
                out = re.sub(rf"\b{re.escape(part)}\b", "[NAME]", out)
    if member_ids:
        out = MEMBER_ID.sub("[MEMBER]", out)
    return out


class PhiFilter(logging.Filter):
    """Redacts PHI in every record of the ``prior_auth`` logger before any handler sees it."""

    def __init__(self, names: Iterable[str]):
        super().__init__()
        self.names = list(names)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage(), self.names, member_ids=True)
        record.args = ()
        return True


def install_log_filter(names: Iterable[str]) -> logging.Logger:
    log = logging.getLogger("prior_auth")
    for f in list(log.filters):
        if isinstance(f, PhiFilter):
            log.removeFilter(f)
    log.addFilter(PhiFilter(names))
    return log
