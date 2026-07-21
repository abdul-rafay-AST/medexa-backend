"""Convert SA file detections into DetectedEntity rows for Path A."""

from __future__ import annotations

from medexa.regions.sa.detection.detector import DetectedSaCode, SaFileDetector
from medexa.schemas import DetectedEntity


class SaEntityExtractor:
    """SA Path A extractor — SBS codes only as billable procedure entities.

    ICD-10-AM detections are returned via ``last_icd_hits`` for insight cards;
    they are not treated as CPT/SBS billable entities.
    """

    def __init__(self, detector: SaFileDetector) -> None:
        self._detector = detector
        self.last_icd_hits: list[DetectedSaCode] = []
        self.last_icd_review_hits: list[DetectedSaCode] = []
        self.last_sbs_hits: list[DetectedSaCode] = []

    @property
    def detector(self) -> SaFileDetector:
        return self._detector

    def extract(self, text: str, chunk_id: str) -> list[DetectedEntity]:
        detected = self._detector.detect_from_transcript(text)
        self.last_sbs_hits = list(detected.sbs_codes)
        self.last_icd_hits = list(detected.icd10_am_codes)
        self.last_icd_review_hits = list(detected.icd10_am_review)

        entities: list[DetectedEntity] = []
        for hit in detected.sbs_codes:
            entities.append(
                DetectedEntity(
                    activity_label=hit.label.replace(" ", "_").lower() if hit.label else hit.code,
                    matched_phrase=hit.matched_text or (hit.matched_phrases[0] if hit.matched_phrases else hit.code),
                    body_region=None,
                    timing_phrase=None,
                    is_billable=True,
                    is_negated=False,
                    possible_cpt=hit.code,
                    source_chunk_id=chunk_id,
                )
            )
        return entities
