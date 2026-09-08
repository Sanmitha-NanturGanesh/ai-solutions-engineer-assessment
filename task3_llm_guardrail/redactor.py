from __future__ import annotations

import re

REDACTED = "[REDACTED]"

EMAIL_RE = re.compile(r"(?i)(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![A-Z0-9.-])")
SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")

# These are intentionally suffix patterns, not complete PII patterns. If the end
# of a chunk still looks like it could become an email/card/SSN, keep it until
# the next chunk arrives.
EMAIL_SUFFIX_RE = re.compile(r"(?i)[A-Z0-9._%+-]+(?:@[A-Z0-9.-]*)?$")
NUMBER_SUFFIX_RE = re.compile(r"[0-9 -]{1,40}$")


def _passes_luhn(value: str) -> bool:
    digits = [int(ch) for ch in value if ch.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False

    total = 0
    parity = len(digits) % 2
    for idx, digit in enumerate(digits):
        if idx % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def redact_pii(text: str) -> str:
    text = EMAIL_RE.sub(REDACTED, text)
    text = SSN_RE.sub(REDACTED, text)
    return CARD_RE.sub(lambda match: REDACTED if _passes_luhn(match.group(0)) else match.group(0), text)


def _unsafe_suffix_start(text: str) -> int:
    """Return the earliest suffix that may still become PII in a later chunk."""
    starts: list[int] = []
    for pattern in (EMAIL_SUFFIX_RE, NUMBER_SUFFIX_RE):
        match = pattern.search(text)
        if match:
            starts.append(match.start())
    return min(starts) if starts else len(text)


class StreamingRedactor:
    """Incremental redactor that keeps only an unfinished PII candidate in memory."""

    def __init__(self, max_carry: int = 320) -> None:
        self._carry = ""
        self._max_carry = max_carry

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""

        self._carry += chunk
        safe_end = _unsafe_suffix_start(self._carry)

        # Protect memory if an upstream emits a pathological token without any
        # delimiter. 320 chars is enough for the PII forms this gateway handles.
        if len(self._carry) - safe_end > self._max_carry:
            safe_end = len(self._carry) - self._max_carry

        safe, self._carry = self._carry[:safe_end], self._carry[safe_end:]
        return redact_pii(safe)

    def flush(self) -> str:
        safe = redact_pii(self._carry)
        self._carry = ""
        return safe
