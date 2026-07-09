from __future__ import annotations

from datetime import datetime

from medexa.core.entity_extractor import EntityExtractor
from medexa.core.suggestion_generator import SuggestionGenerator
from medexa.schemas import DetectedEntity, SessionState, Suggestion, TranscriptChunk


class TranscriptProcessor:
    """Orchestrates the live path for one transcript chunk:
    extract entities -> generate (deduplicated) suggestions -> update state.

    Kept free of FastAPI/AWS so the whole live pipeline is unit-testable.
    """

    def __init__(self, extractor: EntityExtractor, suggestion_generator: SuggestionGenerator):
        self._extractor = extractor
        self._suggestions = suggestion_generator

    def process(
        self,
        state: SessionState,
        chunk: TranscriptChunk,
        now: datetime,
    ) -> tuple[list[DetectedEntity], list[Suggestion]]:
        entities = self._extractor.extract(chunk.text, chunk.chunk_id)
        state.detected_entities.extend(entities)

        new_suggestions = self._suggestions.generate(
            session_id=state.session_id,
            entities=entities,
            existing=state.suggestions,
            now=now,
            active_segments=[
                (seg.cpt_code, seg.body_region)
                for seg in state.timer_segments
                if seg.stop_time is None
            ],
        )
        state.suggestions.extend(new_suggestions)

        return entities, new_suggestions
