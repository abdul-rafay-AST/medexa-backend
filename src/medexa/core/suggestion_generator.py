from __future__ import annotations

import uuid
from datetime import datetime

from medexa.loaders.cpt_metadata_loader import CptMetadataLoader
from medexa.schemas import DetectedEntity, Suggestion, SuggestionAction


class SuggestionGenerator:
    """Turns detected entities into inline CPT suggestion cards (prototype screen 2).

    Deduplication: a CPT+body-region pair is not re-suggested while an existing
    suggestion for it is still ``suggested`` within the cooldown window, or has
    already been ``applied`` (the clinician is already billing it).
    """

    def __init__(self, cpt_metadata_loader: CptMetadataLoader, cooldown_seconds: int = 120):
        self._meta = cpt_metadata_loader
        self._cooldown_seconds = cooldown_seconds

    def generate(
        self,
        session_id: str,
        entities: list[DetectedEntity],
        existing: list[Suggestion],
        now: datetime,
    ) -> list[Suggestion]:
        blocked = self._blocked_keys(existing, now)
        new_suggestions: list[Suggestion] = []

        for entity in entities:
            if not (entity.is_billable and entity.possible_cpt):
                continue

            key = (entity.possible_cpt, entity.body_region)
            if key in blocked:
                continue
            blocked.add(key)  # also dedupe within this same batch

            display = self._meta.get_display_name(entity.possible_cpt)
            new_suggestions.append(
                Suggestion(
                    suggestion_id=str(uuid.uuid4()),
                    session_id=session_id,
                    source_chunk_id=entity.source_chunk_id,
                    suggestion_type="cpt_apply",
                    title=f"Start billing {display} ({entity.possible_cpt})?",
                    message=(
                        f"Detected '{entity.matched_phrase}'"
                        + (f" on {entity.body_region}" if entity.body_region else "")
                        + f" \u2014 apply {entity.possible_cpt}?"
                    ),
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

    def _blocked_keys(
        self, existing: list[Suggestion], now: datetime
    ) -> set[tuple[str | None, str | None]]:
        blocked: set[tuple[str | None, str | None]] = set()
        for s in existing:
            key = (s.cpt_code, s.body_region)
            if s.status == "applied":
                blocked.add(key)
            elif s.status == "suggested":
                age = (now - s.created_at).total_seconds()
                if age < self._cooldown_seconds:
                    blocked.add(key)
        return blocked
