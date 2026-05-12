"""Pre-LLM prompt-injection filter."""
from __future__ import annotations

import re

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+(instructions|rules|prompts?)", re.I),
    re.compile(r"забудь\s+(все\s+)?предыдущие\s+(инструкции|правила)", re.I),
    re.compile(r"reveal\s+(your\s+)?(system\s+)?prompt", re.I),
    re.compile(r"покажи\s+(свой\s+)?(системный\s+)?промпт", re.I),
    re.compile(r"disregard\s+(all\s+)?(prior|previous|above)", re.I),
]


def detect_injection(text: str) -> str | None:
    """Return a warning message if injection pattern detected, else None."""
    for pat in _INJECTION_PATTERNS:
        if pat.search(text):
            return (
                "Your message contains a pattern that looks like a prompt-injection attempt. "
                "This request was blocked. Please rephrase as a normal schedule edit."
            )
    return None
