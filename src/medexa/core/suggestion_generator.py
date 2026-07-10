from __future__ import annotations

import uuid
from datetime import datetime

from medexa.core.ncci_conflict_checker import NcciConflictChecker
from medexa.ports.cpt_metadata import CptMetadataPort
from medexa.schemas import DetectedEntity, Suggestion, SuggestionAction


class SuggestionGenerator:
    """Turns detected entities into inline CPT suggestion cards (prototype screen 2).

    Deduplication: a CPT+body-region pair is permanently blocked while a
    suggestion is ``suggested`` or ``applied``. ``dismissed`` and ``expired``
    suggestions do not block re-detection in a later chunk.
    """

    def __init__(
        self,
        cpt_metadata_loader: CptMetadataPort,
        cooldown_seconds: int = 3600,
        ncci_checker: NcciConflictChecker | None = None,
    ):
        self._meta = cpt_metadata_loader
        self._cooldown_seconds = cooldown_seconds  # retained for API compat; no longer used
        self._ncci = ncci_checker

    def generate(
        self,
        session_id: str,
        entities: list[DetectedEntity],
        existing: list[Suggestion],
        now: datetime,
        active_segments: list[tuple[str, str | None]] | None = None,
    ) -> list[Suggestion]:
        active_segments = active_segments or []
        blocked = self._blocked_keys(existing, now, active_segments)
        new_suggestions: list[Suggestion] = []
        seen_batch: set[tuple[str | None, str | None]] = set()

        for entity in entities:
            if not (entity.is_billable and entity.possible_cpt):
                continue

            key = (entity.possible_cpt, entity.body_region)
            if key in blocked or key in seen_batch:
                continue
            seen_batch.add(key)

            display = self._meta.get_display_name(entity.possible_cpt)
            message = (
                f"Detected '{entity.matched_phrase}'"
                + (f" on {entity.body_region}" if entity.body_region else "")
                + f" \u2014 apply {entity.possible_cpt}?"
            )
            ncci_note = self._ncci_warning(entity.possible_cpt, entity.body_region, active_segments)
            if ncci_note:
                message = f"{message} {ncci_note}"

            new_suggestions.append(
                Suggestion(
                    suggestion_id=str(uuid.uuid4()),
                    session_id=session_id,
                    source_chunk_id=entity.source_chunk_id,
                    suggestion_type="cpt_apply",
                    title=f"Start billing {display} ({entity.possible_cpt})?",
                    message=message,
                    cpt_code=entity.possible_cpt,
                    body_region=entity.body_region,
                    actions=[
                        SuggestionAction(label="Apply", action_type="apply"),
                        SuggestionAction(label="Add duration", action_type="set_duration"),
                        SuggestionAction(label="Dismiss", action_type="dismiss"),
                    ],
                    created_at=now,
                )
            )

        return new_suggestions

    def _ncci_warning(
        self,
        cpt_code: str,
        body_region: str | None,
        active_segments: list[tuple[str, str | None]],
    ) -> str:
        if self._ncci is None:
            return ""
        for seg_cpt, seg_region in active_segments:
            if seg_cpt == cpt_code:
                continue
            rule = self._ncci.check_conflict(cpt_code, seg_cpt)
            if not rule:
                continue
            if rule["body_region_sensitive"]:
                if body_region is None or body_region != seg_region:
                    continue
            modifier = " Modifier 59 may apply." if rule.get("modifier_59_possible") else ""
            return f"[NCCI warning vs {seg_cpt}: {rule['explanation']}{modifier}]"
        return ""

    def _blocked_keys(
        self,
        existing: list[Suggestion],
        now: datetime,
        active_segments: list[tuple[str, str | None]],
    ) -> set[tuple[str | None, str | None]]:
        del now  # cooldown removed — block is idempotent by status
        blocked: set[tuple[str | None, str | None]] = set()
        for s in existing:
            if s.status in ("dismissed", "expired") or not s.cpt_code:
                continue
            blocked.add((s.cpt_code, s.body_region))
            blocked.add((s.cpt_code, None))
        for seg_cpt, seg_region in active_segments:
            blocked.add((seg_cpt, seg_region))
            blocked.add((seg_cpt, None))
        return blocked
