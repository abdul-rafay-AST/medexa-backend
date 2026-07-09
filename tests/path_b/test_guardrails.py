from __future__ import annotations

import pytest

from medexa.adapters.guardrails.local_guardrails import LocalGuardrails


def test_scrub_phi_masks_ssn_and_email() -> None:
    guardrails = LocalGuardrails()
    text = "Patient email alice@clinic.com and SSN 123-45-6789 noted."
    scrubbed = guardrails.scrub_phi(text)
    assert "alice@clinic.com" not in scrubbed
    assert "123-45-6789" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_validate_assistant_output_rejects_billing_assertion() -> None:
    guardrails = LocalGuardrails()
    with pytest.raises(ValueError, match="billing CPT"):
        guardrails.validate_assistant_output("Please bill code 97110 now.")


def test_validate_assistant_output_appends_disclaimer() -> None:
    guardrails = LocalGuardrails()
    result = guardrails.validate_assistant_output("Document pain scale.")
    assert "AI-generated suggestions require clinician review" in result
