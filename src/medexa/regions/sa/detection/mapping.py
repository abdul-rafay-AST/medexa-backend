"""SBS ↔ ICD-10-AM medical-necessity validation from mapping flatfile."""

from __future__ import annotations

from dataclasses import dataclass

from medexa.regions.sa.detection.catalog import SaBillingCatalog


@dataclass(frozen=True)
class MappingValidation:
    sbs_code: str
    status: str  # valid | pending_review | valid_no_crosswalk
    matched_icd: str | None = None
    reason: str = ""


def validate_sbs_icd_mapping(
    sbs_codes: list[str],
    icd_codes: list[str],
    catalog: SaBillingCatalog,
) -> list[MappingValidation]:
    """Flag SBS lines missing a linked ICD; does not auto-remove codes."""
    ranked = list(dict.fromkeys(icd_codes))
    results: list[MappingValidation] = []

    for sbs in sorted(set(sbs_codes)):
        valid_set = catalog.sbs_icd_mapping.get(sbs)
        if valid_set is None:
            results.append(
                MappingValidation(
                    sbs_code=sbs,
                    status="valid_no_crosswalk",
                    reason="No SBS–ICD-10-AM mapping entry; medical necessity not auto-checked.",
                )
            )
            continue

        if not valid_set:
            results.append(
                MappingValidation(
                    sbs_code=sbs,
                    status="pending_review",
                    reason="Mapping entry has no direct ICD codes; clinician review required.",
                )
            )
            continue

        eligible = [icd for icd in ranked if icd in valid_set]
        if eligible:
            matched = eligible[0]
            results.append(
                MappingValidation(
                    sbs_code=sbs,
                    status="valid",
                    matched_icd=matched,
                    reason=(
                        f"Detected ICD {matched} is on the medical necessity mapping for {sbs}."
                    ),
                )
            )
        else:
            results.append(
                MappingValidation(
                    sbs_code=sbs,
                    status="pending_review",
                    reason=(
                        f"{sbs} is not on the direct auto-approve list for any "
                        f"detected ICD. Confirm before billing."
                    ),
                )
            )

    return results
