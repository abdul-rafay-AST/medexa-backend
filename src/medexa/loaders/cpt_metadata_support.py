from __future__ import annotations

from typing import Any, Mapping

from medexa.schemas import Confidence, CptSuggestionDetail


def meta_str(meta: Mapping[str, Any] | None, key: str, default: str = "") -> str:
    if meta is None:
        return default
    value = meta.get(key, default)
    return str(value) if value is not None else default


def meta_confidence(meta: Mapping[str, Any] | None, default: Confidence = "high") -> Confidence:
    raw = meta_str(meta, "confidence", default)
    if raw in ("low", "medium", "high"):
        return raw  # type: ignore[return-value]
    return default


def cpt_detail_from_entity(
    *,
    code: str,
    matched_phrase: str,
    metadata: Mapping[str, Any] | None,
    display_name: str,
    reason: str | None = None,
) -> CptSuggestionDetail:
    return CptSuggestionDetail(
        code=code,
        label=meta_str(metadata, "label", code),
        display_name=display_name,
        descriptor=meta_str(metadata, "descriptor", ""),
        matched_phrases=[matched_phrase],
        documentation_requirements=list(metadata.get("documentation_requirements", [])) if metadata else [],
        billing_caveats=dict(metadata.get("billing_caveats", {})) if metadata else {},
        reason=reason or meta_str(metadata, "clinical_rationale", "Detected billable activity in transcript."),
        confidence=meta_confidence(metadata),
    )
