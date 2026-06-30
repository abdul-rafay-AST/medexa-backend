import re
from typing import List

from medexa.schemas import DetectedEntity
from medexa.loaders.activity_synonym_loader import ActivitySynonymLoader
from medexa.loaders.body_region_normalizer import BodyRegionNormalizer
from medexa.loaders.cpt_lookup_loader import CptLookupLoader


class EntityExtractor:
    """
    Extracts clinical activities, body regions, and timing phrases from raw transcript text.
    Operates statelessly and deterministically using simple rule-based pattern matching.
    """

    def __init__(
        self,
        synonym_loader: ActivitySynonymLoader,
        region_normalizer: BodyRegionNormalizer,
        cpt_loader: CptLookupLoader,
    ):
        self._synonym_loader = synonym_loader
        self._region_normalizer = region_normalizer
        self._cpt_loader = cpt_loader

        # Healthcare Compliance: This regex explicitly looks for clinical/activity terms.
        # It DOES NOT attempt to extract names, SSNs, DOBs, or any PHI/PII.
        self._timing_pattern = re.compile(
            r"\b(\d+\s*(?:minutes?|mins?|weeks?|days?))\b", re.IGNORECASE
        )
        # NOTE: "stop"/"pause" are intentionally NOT negation words. They are
        # session-control terms (Pause/Stop buttons) and must not be interpreted
        # as clinical negation of an activity.
        self._negation_pattern = re.compile(
            r"\b(not|no|denies|without|discontinue)\b", re.IGNORECASE
        )

    def extract(self, text: str, chunk_id: str) -> List[DetectedEntity]:
        """Scans the text chunk and returns a list of detected clinical entities."""
        entities: List[DetectedEntity] = []
        text_lower = text.lower()

        # 1. Detect negation (chunk-level for MVP simplicity).
        is_negated = bool(self._negation_pattern.search(text_lower))

        # 2. Extract timing.
        timing_match = self._timing_pattern.search(text_lower)
        timing_phrase = timing_match.group(1) if timing_match else None

        # 3. Detect body region (first match for MVP).
        detected_region = self._region_normalizer.find_region(text_lower)

        # 4. Detect activities and map each to a CPT code.
        for matched_phrase, activity_label in self._synonym_loader.find_matches(text_lower):
            # CPT table is keyed by clinical phrase; activity labels are the fallback.
            possible_cpt = self._cpt_loader.get_cpt_for_activity(matched_phrase) or (
                self._cpt_loader.get_cpt_for_activity(activity_label)
            )
            # Billable only when it maps to a CPT and isn't negated.
            is_billable = possible_cpt is not None and not is_negated

            entities.append(
                DetectedEntity(
                    activity_label=activity_label,
                    matched_phrase=matched_phrase,
                    body_region=detected_region,
                    timing_phrase=timing_phrase,
                    is_billable=is_billable,
                    is_negated=is_negated,
                    possible_cpt=possible_cpt,
                    source_chunk_id=chunk_id,
                )
            )

        return entities
