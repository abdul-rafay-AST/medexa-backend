import re
from typing import List

from medexa.schemas import DetectedEntity
from medexa.loaders.body_region_normalizer import BodyRegionNormalizer
from medexa.loaders.hybrid_cpt_rule_index import HybridCptRuleIndex


class EntityExtractor:
    """Extracts clinical activities from transcript text using the hybrid CPT index.

    Healthcare compliance: does not extract PHI — only clinical activity phrases.
    """

    def __init__(
        self,
        cpt_index: HybridCptRuleIndex,
        region_normalizer: BodyRegionNormalizer,
    ):
        self._cpt_index = cpt_index
        self._region_normalizer = region_normalizer

        self._timing_pattern = re.compile(
            r"\b(\d+\s*(?:minutes?|mins?|weeks?|days?))\b", re.IGNORECASE
        )
        self._negation_pattern = re.compile(
            r"\b(not|no|denies|without|discontinue)\b", re.IGNORECASE
        )

    def extract(self, text: str, chunk_id: str) -> List[DetectedEntity]:
        entities: List[DetectedEntity] = []
        text_lower = text.lower()
        is_negated = bool(self._negation_pattern.search(text_lower))
        timing_match = self._timing_pattern.search(text_lower)
        timing_phrase = timing_match.group(1) if timing_match else None
        detected_region = self._region_normalizer.find_region(text_lower)

        for match in self._cpt_index.match(text_lower):
            activity_label = match.activity_label or match.phrase.replace(" ", "_")
            is_billable = not is_negated
            entities.append(
                DetectedEntity(
                    activity_label=activity_label,
                    matched_phrase=match.phrase,
                    body_region=detected_region,
                    timing_phrase=timing_phrase,
                    is_billable=is_billable,
                    is_negated=is_negated,
                    possible_cpt=match.cpt_code if is_billable else None,
                    source_chunk_id=chunk_id,
                )
            )

        return entities
