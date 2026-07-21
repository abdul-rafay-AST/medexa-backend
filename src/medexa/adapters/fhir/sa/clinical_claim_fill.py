"""Clinical fill for SA NPHIES Claim / PriorAuth bundles (BillingEngine parity).

Populates:
- ``Claim.diagnosis`` from session ICD insights (approved + auto-detect)
- ``Claim.item`` from billing summary lines + detected SBS insights
- per-item ``diagnosisSequence`` via SBS→ICD Direct mapping when available
- narrative supportingInfo (treatment-plan, HPI, chief-complaint)

Pricing / coverage / vitals remain template placeholders.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from medexa.adapters.fhir._common import find_extension
from medexa.regions.sa.detection.catalog import SaBillingCatalog
from medexa.schemas import BillingSummary, SessionState

_PACKAGE_PREFIXES = ("98010-", "98014-", "98016-")
_ICD_SYSTEM = "http://hl7.org/fhir/sid/icd-10-am"
_SERVICES_CS = "http://nphies.sa/terminology/CodeSystem/services"
_DX_TYPE_CS = "http://nphies.sa/terminology/CodeSystem/diagnosis-type"


def is_package_code(code: str) -> bool:
    return any((code or "").startswith(p) for p in _PACKAGE_PREFIXES)


def _icd_variants(icd: str) -> list[str]:
    icd = (icd or "").strip()
    if not icd:
        return []
    variants = [icd]
    if "." in icd:
        base, dec = icd.split(".", 1)
        if dec and dec[-1] == "0" and len(dec) > 1:
            variants.append(f"{base}.{dec.rstrip('0')}")
        if len(dec) < 2:
            variants.append(f"{base}.{dec}0")
    else:
        variants.append(f"{icd}.0")
    return list(dict.fromkeys(variants))


def _icd_in_set(icd: str, valid_set: set[str]) -> bool:
    return any(v in valid_set for v in _icd_variants(icd))


def _insight_icd_display(insight_label: str, code: str, catalog: SaBillingCatalog | None) -> str:
    if insight_label and insight_label not in {"ICD-10-AM", "ICD-10-AM (Review)"}:
        # Prefer question/label only when it looks like a clinical name (not the card chrome).
        if code and code in insight_label:
            pass
        elif not insight_label.startswith("ICD"):
            return insight_label
    if catalog is not None:
        return catalog.icd_display_name(code)
    return code


def collect_session_icd_codes(
    state: SessionState,
    catalog: SaBillingCatalog | None = None,
) -> list[tuple[str, str]]:
    """Ordered (code, display) for Claim.diagnosis — BillingEngine ``state.icds`` analogue.

    Includes:
    - approved ``detected_icd`` insights
    - auto-detect pending (not ``review_recommended``, not ignored)
    - explicit ``state.claim.diagnoses`` overrides
    """
    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(code: str, display: str = "") -> None:
        code = (code or "").strip()
        if not code or code in seen:
            return
        seen.add(code)
        label = display.strip() if display else ""
        if not label and catalog is not None:
            label = catalog.icd_display_name(code)
        ordered.append((code, label or code))

    for insight in state.insights:
        if insight.type != "detected_icd" or not insight.code:
            continue
        if insight.status == "ignored":
            continue
        if insight.status == "approved":
            _add(insight.code, _insight_icd_display(insight.label, insight.code, catalog))

    for insight in state.insights:
        if insight.type != "detected_icd" or not insight.code:
            continue
        if insight.status in {"ignored", "approved"}:
            continue
        if insight.validation_status == "review_recommended":
            continue
        _add(insight.code, _insight_icd_display(insight.label, insight.code, catalog))

    for dx in state.claim.diagnoses:
        _add(dx.code, dx.description)

    return ordered


def collect_treatment_lines(
    state: SessionState,
    summary: BillingSummary,
    catalog: SaBillingCatalog | None = None,
) -> list[tuple[str, str, int]]:
    """Ordered (code, display, units) — timer billable lines + detected SBS insights."""
    lines: list[tuple[str, str, int]] = []
    seen: set[str] = set()

    def _add(code: str, display: str, units: int) -> None:
        code = (code or "").strip()
        if not code or code in seen:
            return
        seen.add(code)
        if not display and catalog is not None:
            display = catalog.sbs_display_name(code)
        qty = int(units) if units and units > 0 else 1
        lines.append((code, display or code, qty))

    for line in summary.line_items:
        _add(line.cpt_code, line.display_name, line.units)

    for insight in state.insights:
        if insight.type != "detected" or not insight.code:
            continue
        if insight.status == "ignored":
            continue
        display = ""
        if catalog is not None:
            display = catalog.sbs_display_name(insight.code)
        if not display and insight.label and insight.label != "Detected SBS":
            display = insight.label
        _add(insight.code, display, 1)

    return lines


def build_diagnosis_rows(
    state: SessionState,
    catalog: SaBillingCatalog | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, (code, display) in enumerate(collect_session_icd_codes(state, catalog), start=1):
        dx_type = "principal" if i == 1 else "secondary"
        rows.append(
            {
                "sequence": i,
                "diagnosisCodeableConcept": {
                    "coding": [
                        {
                            "system": _ICD_SYSTEM,
                            "code": code,
                            "display": display,
                        }
                    ]
                },
                "type": [
                    {
                        "coding": [
                            {
                                "system": _DX_TYPE_CS,
                                "code": dx_type,
                            }
                        ]
                    }
                ],
            }
        )
    return rows


def _diagnosis_sequences_for_sbs(
    sbs_code: str,
    icd_to_sequence: dict[str, int],
    catalog: SaBillingCatalog | None,
) -> list[int]:
    all_seqs = list(icd_to_sequence.values())
    if not all_seqs:
        return [1]
    if catalog is None:
        return all_seqs
    valid_set = catalog.sbs_icd_mapping.get(sbs_code)
    if not valid_set:
        return all_seqs
    linked = [
        seq for code, seq in icd_to_sequence.items() if _icd_in_set(code, valid_set)
    ]
    return linked or all_seqs


def build_item_rows(
    state: SessionState,
    summary: BillingSummary,
    *,
    template_item: dict[str, Any],
    diagnosis_rows: list[dict[str, Any]],
    catalog: SaBillingCatalog | None = None,
    serviced_date: str,
    include_patient_invoice: bool = True,
) -> list[dict[str, Any]]:
    icd_to_sequence = {
        str(d["diagnosisCodeableConcept"]["coding"][0]["code"]): int(d["sequence"])
        for d in diagnosis_rows
        if d.get("diagnosisCodeableConcept", {}).get("coding")
    }
    items: list[dict[str, Any]] = []
    for index, (code, display, units) in enumerate(
        collect_treatment_lines(state, summary, catalog), start=1
    ):
        item = deepcopy(template_item)
        item["sequence"] = index
        item["careTeamSequence"] = [1]
        item["diagnosisSequence"] = _diagnosis_sequences_for_sbs(
            code, icd_to_sequence, catalog
        )
        item["servicedDate"] = serviced_date
        item.setdefault("productOrService", {}).setdefault("coding", [{}])
        coding = item["productOrService"]["coding"]
        if not coding:
            coding.append({})
        coding[0]["system"] = _SERVICES_CS
        coding[0]["code"] = code
        coding[0]["display"] = display
        item["quantity"] = {"value": units}

        for ext in item.get("extension", []) or []:
            url = str(ext.get("url") or "")
            if url.endswith("extension-package"):
                ext["valueBoolean"] = is_package_code(code)
            if url.endswith("extension-maternity"):
                ext["valueBoolean"] = False
            if "valueMoney" in ext:
                money = ext.get("valueMoney") or {}
                if "value" in money:
                    money["value"] = None
                ext["valueMoney"] = money

        if include_patient_invoice:
            invoice_ext = find_extension(item, "extension-patientInvoice")
            if invoice_ext is not None:
                invoice_ext.setdefault("valueIdentifier", {})
                invoice_ext["valueIdentifier"]["system"] = (
                    "https://medexa.internal/identifiers/patient-invoice"
                )
                invoice_ext["valueIdentifier"]["value"] = f"{summary.session_id}-{index}"

        if "unitPrice" in item and isinstance(item["unitPrice"], dict):
            item["unitPrice"]["value"] = None
        if "net" in item and isinstance(item["net"], dict):
            item["net"]["value"] = None

        items.append(item)
    return items


def fill_clinical_supporting_info(
    claim: dict[str, Any],
    state: SessionState,
    diagnosis_rows: list[dict[str, Any]],
    item_rows: list[dict[str, Any]],
) -> None:
    dx_text = "; ".join(
        f"{d['diagnosisCodeableConcept']['coding'][0]['code']} "
        f"({d['diagnosisCodeableConcept']['coding'][0]['display']})"
        for d in diagnosis_rows
    )
    tx_text = "; ".join(
        f"{it['productOrService']['coding'][0]['code']} "
        f"({it['productOrService']['coding'][0]['display']})"
        for it in item_rows
    )
    transcript = (state.transcript_text or "").strip()
    hpi = transcript[:500] if transcript else dx_text

    for info in claim.get("supportingInfo") or []:
        category = ""
        for coding in (info.get("category") or {}).get("coding") or []:
            category = str(coding.get("code") or "")
            if category:
                break
        if category == "history-of-present-illness" and hpi:
            info["valueString"] = hpi
        elif category == "treatment-plan" and tx_text:
            info["valueString"] = tx_text
        elif category == "chief-complaint" and diagnosis_rows:
            principal = diagnosis_rows[0]["diagnosisCodeableConcept"]["coding"][0]
            info["code"] = info.get("code") or {}
            coding = info["code"].setdefault("coding", [{}])
            if not coding:
                coding.append({})
            coding[0]["system"] = _ICD_SYSTEM
            coding[0]["code"] = principal["code"]
            coding[0]["display"] = principal["display"]


def _serviced_date(state: SessionState, summary: BillingSummary) -> str:
    when: datetime | None = summary.generated_at or state.created_at
    if when is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return when.date().isoformat()


def apply_clinical_claim_fill(
    claim: dict[str, Any],
    state: SessionState,
    summary: BillingSummary,
    catalog: SaBillingCatalog | None = None,
    *,
    include_patient_invoice: bool = True,
) -> None:
    """Replace skeleton diagnosis/items with session clinical content."""
    diagnosis_rows = build_diagnosis_rows(state, catalog)
    claim["diagnosis"] = diagnosis_rows

    template_item = deepcopy(claim["item"][0]) if claim.get("item") else {
        "extension": [],
        "sequence": 1,
        "careTeamSequence": [1],
        "diagnosisSequence": [1],
        "productOrService": {"coding": [{"system": "", "code": "", "display": ""}]},
        "servicedDate": _serviced_date(state, summary),
        "quantity": {"value": 1},
        "unitPrice": {"value": None, "currency": "SAR"},
        "net": {"value": None, "currency": "SAR"},
        "informationSequence": [],
    }

    items = build_item_rows(
        state,
        summary,
        template_item=template_item,
        diagnosis_rows=diagnosis_rows,
        catalog=catalog,
        serviced_date=_serviced_date(state, summary),
        include_patient_invoice=include_patient_invoice,
    )
    claim["item"] = items

    fill_clinical_supporting_info(claim, state, diagnosis_rows, items)

    if "total" in claim and isinstance(claim["total"], dict):
        claim["total"]["value"] = None
