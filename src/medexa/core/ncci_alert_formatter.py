"""Standard NCCI conflict messages for alerts, insights, and SOAP billing notes."""

from __future__ import annotations

from medexa.loaders.ncci_rules_loader import NcciRule


def format_ncci_conflict_message(
    cpt_a: str,
    cpt_b: str,
    *,
    body_region: str | None,
    rule: NcciRule,
) -> str:
    """Human-readable NCCI alert with Modifier 59 guidance when applicable."""
    region_label = _format_body_region(body_region)
    indicator = _ncci_indicator_label(rule)
    base = (
        f"{cpt_a} and {cpt_b} performed on {region_label} (same body region). "
        f"These codes are bundled under NCCI {indicator}."
    )
    if rule.get("modifier_59_possible"):
        return (
            f"{base} Apply Modifier 59 if services were distinct and separate. "
            f"{rule['explanation']}"
        )
    return f"{base} {rule['explanation']}"


def _ncci_indicator_label(rule: NcciRule) -> str:
    if rule.get("modifier_59_possible"):
        return "Indicator 0 (modifier allowed when distinct)"
    return "Indicator 1 (bundled)"


def _format_body_region(region: str | None) -> str:
    if not region:
        return "the same body region"
    normalized = region.replace("_", " ").replace("-", " ")
    return normalized
