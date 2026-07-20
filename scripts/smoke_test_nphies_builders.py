"""Smoke-test the SA claim + prior-auth bundle builders against compliance checks."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from medexa.adapters.fhir.sa.claim_bundle_builder import NphiesClaimBundleBuilder
from medexa.adapters.fhir.sa.priorauth_bundle_builder import NphiesPriorAuthBundleBuilder
from medexa.regions.sa.bundle import build_sa_bundle
from medexa.schemas import BillingLineItem, BillingSummary, SessionState

CONFIG_ROOT = ROOT / "config"
CPT_DIR = ROOT / "data" / "cpt_files"


def make_state() -> SessionState:
    return SessionState(
        session_id="SESSION-0001",
        billing_region="SA",
        patient_id="PAT-0001",
        patient_name="Ahmed Al-Otaibi",
        mrn="MRN-0001",
        therapist_id="TH-LICENSE-1234",
        payer_id="PAYER-LICENSE-99",
        member_id="MEMBER-0001",
        pre_auth_reference="PA-REF-0001",
    )


def make_summary() -> BillingSummary:
    return BillingSummary(
        session_id="SESSION-0001",
        total_minutes=30,
        total_units=2,
        line_items=[
            BillingLineItem(
                cpt_code="95550-03-00",
                display_name="Allied health intervention, physiotherapy",
                timed=True,
                total_seconds=1800,
                units=2,
            )
        ],
        generated_at=datetime.now(timezone.utc),
    )


def check(condition: bool, message: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {message}")
    if not condition:
        raise SystemExit(1)


def validate_claim(bundle: dict) -> None:
    text = json.dumps(bundle)
    check(bundle["resourceType"] == "Bundle", "claim: resourceType is Bundle")
    check(bundle["type"] == "message", "claim: type is message")
    check("extension-episode" in text, "claim: has extension-episode")
    check("extension-patientInvoice" in text, "claim: has extension-patientInvoice")
    check("extension-maternity" in text, "claim: has extension-maternity")
    check(text.count("claim-information-category") >= 14, "claim: full 14-category supportingInfo")
    check("http://nphies.sa/terminology/CodeSystem/services" in text, "claim: uses services CodeSystem")
    check("http://nphies.sa/terminology/CodeSystem/procedures" not in text, "claim: no procedures CodeSystem")
    check("encounter-claim-AMB" in text, "claim: encounter-claim-AMB profile")
    check('"op"' in text, "claim: subType is op")
    check(bundle["entry"][0]["resource"]["eventCoding"]["code"] == "claim-request", "claim: eventCoding claim-request")
    claim_resource = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Claim")
    print("SESSION-0001 claim identifier ->", claim_resource["identifier"][0]["value"])


def validate_priorauth(bundle: dict) -> None:
    text = json.dumps(bundle)
    check(bundle["resourceType"] == "Bundle", "priorauth: resourceType is Bundle")
    check("extension-eligibility-response" in text, "priorauth: has extension-eligibility-response")
    check("extension-episode" not in text, "priorauth: no extension-episode (not required)")
    check("http://nphies.sa/terminology/CodeSystem/services" in text, "priorauth: uses services CodeSystem")
    check("http://nphies.sa/terminology/CodeSystem/procedures" not in text, "priorauth: no procedures CodeSystem")
    check("encounter-auth-AMB" in text, "priorauth: encounter-auth-AMB profile")
    check('"op"' in text, "priorauth: subType is op")
    check('"valueBoolean": false' in text, "priorauth: package/maternity default false")
    check('"valueBoolean": true' not in text, "priorauth: no defaulted true booleans")
    claim_resource = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Claim")
    print("SESSION-0001 priorauth identifier ->", claim_resource["identifier"][0]["value"])


def main() -> None:
    region_bundle = build_sa_bundle(CONFIG_ROOT, CPT_DIR)
    state = make_state()
    summary = make_summary()

    claim_builder = NphiesClaimBundleBuilder(bundle=region_bundle)
    claim_bundle = claim_builder.build_claim_bundle(state, summary)
    validate_claim(claim_bundle)

    priorauth_builder = NphiesPriorAuthBundleBuilder(bundle=region_bundle)
    priorauth_bundle = priorauth_builder.build_priorauth_bundle(state, summary)
    validate_priorauth(priorauth_bundle)

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
