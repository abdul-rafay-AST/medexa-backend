"""SA package-tier resolution after timer stop/end/switch."""

from __future__ import annotations

from medexa.api.mappers import _insight_id
from medexa.regions.sa.billing.package_tier import is_package_code, resolve_package_tier
from medexa.regions.sa.detection.catalog import SaBillingCatalog
from medexa.regions.sa.detection.mapping import validate_sbs_icd_mapping
from medexa.schemas import SessionState


def _package_stem(code: str) -> str:
    """Extract 5-char prefix like '98014' from '98014-00-10'."""
    return code[:5] if len(code) >= 5 else code


def resolve_packages_after_stop(
    state: SessionState,
    catalog: SaBillingCatalog,
) -> list[str]:
    """Resolve stopped SA package parents to duration-based children.

    Aggregates total accumulated_seconds across ALL stopped segments sharing
    the same package stem (e.g. all ``98014-*`` segments), then rewrites every
    segment in that group to the resolved child code.

    Also rewrites matching ``detected`` insights (code + insight_id + text)
    so approve/ignore identity stays consistent with billing lines.

    Returns list of resolved child codes (empty if nothing changed).
    """
    if state.billing_region != "SA":
        return []

    stems: dict[str, list] = {}
    for seg in state.timer_segments:
        if seg.stop_time is None:
            continue
        if not is_package_code(seg.cpt_code):
            continue
        stem = _package_stem(seg.cpt_code)
        stems.setdefault(stem, []).append(seg)

    if not stems:
        return []

    resolved_codes: list[str] = []
    for stem, segments in stems.items():
        total_seconds = sum(seg.accumulated_seconds for seg in segments)
        total_minutes = total_seconds / 60.0
        resolved = resolve_package_tier(segments[0].cpt_code, total_minutes)
        any_changed = False
        for seg in segments:
            if seg.cpt_code != resolved:
                seg.cpt_code = resolved
                any_changed = True
        if any_changed:
            resolved_codes.append(resolved)
            if state.active_cpt and _package_stem(state.active_cpt) == stem:
                state.active_cpt = resolved
            for insight in state.insights:
                if (
                    insight.type == "detected"
                    and insight.code
                    and is_package_code(insight.code)
                    and _package_stem(insight.code) == stem
                    and insight.code != resolved
                ):
                    old_code = insight.code
                    insight.code = resolved
                    insight.insight_id = _insight_id("detected", resolved)
                    insight.question = insight.question.replace(old_code, resolved)
                    if insight.label and old_code in insight.label:
                        insight.label = insight.label.replace(old_code, resolved)

    if resolved_codes:
        approved_icd = [
            i.code
            for i in state.insights
            if i.type == "detected_icd" and i.status == "approved" and i.code
        ]
        auto_icd = [
            i.code
            for i in state.insights
            if i.type == "detected_icd"
            and i.validation_status != "review_recommended"
            and i.code
        ]
        all_icd = list(dict.fromkeys(approved_icd + auto_icd))
        validations = validate_sbs_icd_mapping(resolved_codes, all_icd, catalog)
        for v in validations:
            for insight in state.insights:
                if insight.type == "detected" and insight.code == v.sbs_code:
                    insight.validation_status = v.status

    return resolved_codes
