from __future__ import annotations

from medexa.api import contracts as c
from medexa.api import mappers as m
from medexa.loaders.cpt_metadata_support import cpt_detail_from_entity
from medexa.loaders.icd_lookup_loader import IcdLookupLoader
from medexa.loaders.ncci_rules_loader import NcciRulesLoader
from medexa.ports.cpt_metadata import CptMetadataPort
from medexa.schemas import (
    ClinicalAnalysis,
    CptSuggestionDetail,
    SessionState,
)
from medexa.services.clinical_analyzer import RulesClinicalAnalyzer

_DISCLAIMER = "Rules-based detection requires clinician review before billing."


class PathAClinicalSnapshotBuilder:
    """Builds the chunk API response from Path A state only — no Bedrock/LLM."""

    def __init__(
        self,
        rules_analyzer: RulesClinicalAnalyzer,
        icd_loader: IcdLookupLoader,
        ncci_loader: NcciRulesLoader,
        metadata: CptMetadataPort,
    ) -> None:
        self._rules = rules_analyzer
        self._icd = icd_loader
        self._ncci = ncci_loader
        self._meta = metadata

    def build_analysis(
        self, state: SessionState, chunk_text: str, chunk_id: str | None = None
    ) -> ClinicalAnalysis:
        """Rules-only clinical snapshot for wire contract (symptoms/ICD/NCCI from flat files)."""
        base = self._rules.analyze(chunk_text)
        cpt_from_state = self._cpt_suggestions_from_entities(state, chunk_text, chunk_id)
        merged_cpt = self._merge_cpt_suggestions(base.cpt_suggestions, cpt_from_state)
        return base.model_copy(update={"cpt_suggestions": merged_cpt, "disclaimer": _DISCLAIMER})

    def to_contract(self, analysis: ClinicalAnalysis, state: SessionState) -> c.ApiTranscriptAnalysis:
        return m.analysis_to_contract(analysis, state=state)

    def _cpt_suggestions_from_entities(
        self, state: SessionState, chunk_text: str, chunk_id: str | None = None
    ) -> list[CptSuggestionDetail]:
        if chunk_id is None and state.transcript_chunks:
            chunk_id = state.transcript_chunks[-1].chunk_id
        seen: set[str] = set()
        details: list[CptSuggestionDetail] = []
        for entity in state.detected_entities:
            if chunk_id and entity.source_chunk_id != chunk_id:
                continue
            code = entity.possible_cpt
            if not code or code in seen or entity.is_negated:
                continue
            seen.add(code)
            meta = self._meta.get(code)
            details.append(
                cpt_detail_from_entity(
                    code=code,
                    matched_phrase=entity.matched_phrase,
                    metadata=meta,
                    display_name=self._meta.get_display_name(code),
                    reason=f"Detected '{entity.matched_phrase}' in transcript.",
                )
            )
        if not details and chunk_text:
            return []
        return details

    @staticmethod
    def _merge_cpt_suggestions(
        existing: list[CptSuggestionDetail], from_entities: list[CptSuggestionDetail]
    ) -> list[CptSuggestionDetail]:
        by_code = {s.code: s for s in existing}
        for item in from_entities:
            if item.code not in by_code:
                by_code[item.code] = item
        return list(by_code.values())
