from __future__ import annotations

import re


_PHI_PATTERNS = (
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN-shaped
    re.compile(r"\b\d{10,}\b"),  # long numeric ids
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),  # email
)

_BILLING_ASSERTION = re.compile(
    r"\b(bill|code|charge)\s+(971\d{2}|975\d{2}|970\d{2})\b", re.I
)

_DISCLAIMER = "AI-generated suggestions require clinician review before use."


class LocalGuardrails:
    """Path B/C guardrails without AWS Bedrock Guardrails (Phase 3)."""

    def scrub_phi(self, text: str) -> str:
        scrubbed = text
        for pattern in _PHI_PATTERNS:
            scrubbed = pattern.sub("[REDACTED]", scrubbed)
        return scrubbed

    def validate_assistant_output(self, text: str) -> str:
        if _BILLING_ASSERTION.search(text):
            raise ValueError("Assistant output must not assert billing CPT codes (Path A only).")
        if _DISCLAIMER not in text:
            return f"{text.rstrip()}\n\n{_DISCLAIMER}"
        return text
