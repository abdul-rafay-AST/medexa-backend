from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from medexa.application.regional_path_a_service import RegionalPathAService
from medexa.core.billing_timer_engine import BillingTimerEngine
from medexa.core.insights_builder import InsightsBuilder, _alert_key
from medexa.core.ncci_conflict_checker import NcciConflictChecker
from medexa.core.transcript_processor import TranscriptProcessor
from medexa.domain.events import (
    ActivityChanged,
    BodyRegionChanged,
    ChunkProcessed,
    CodeConflictFound,
    CptDetected,
    DocumentationGapDetected,
    DomainEvent,
    NcciConflictFound,
    PathAAlertRaised,
    PreAuthViolationFound,
)
from medexa.domain.transcript_timeline import TimelineEvent
from medexa.ports.cpt_metadata import CptMetadataPort
from medexa.regions.sa.detection.entity_extractor import SaEntityExtractor
from medexa.regions.sa.detection.mapping import validate_sbs_icd_mapping
from medexa.schemas import Alert, DetectedEntity, InsightsPanel, ProtocolInsight, SessionState, TranscriptChunk
from medexa.api import mappers as m


@dataclass
class PathAResult:
    chunk: TranscriptChunk
    entities: list[DetectedEntity]
    panel: InsightsPanel
    events: list[DomainEvent]
    new_alerts: list[Alert]


class PathAProcessor:
    def __init__(
        self,
        transcript_processor: TranscriptProcessor,
        insights_builder: InsightsBuilder,
        ncci_checker: NcciConflictChecker,
        metadata: CptMetadataPort,
        timer_engine: BillingTimerEngine,
        *,
        enable_ncci: bool = True,
        regional_path_a: RegionalPathAService | None = None,
        sa_extractor: SaEntityExtractor | None = None,
    ) -> None:
        self._processor = transcript_processor
        self._insights = insights_builder
        self._ncci = ncci_checker
        self._meta = metadata
        self._timers = timer_engine
        self._enable_ncci = enable_ncci
        self._regional = regional_path_a
        self._sa_extractor = sa_extractor

    def process(
        self,
        state: SessionState,
        chunk: TranscriptChunk,
        now: datetime,
    ) -> PathAResult:
        prior_cpts = {e.possible_cpt for e in state.detected_entities if e.possible_cpt}
        prior_suggestion_cpts = {s.cpt_code for s in state.suggestions if s.cpt_code}
        session_seen_cpts = prior_cpts | prior_suggestion_cpts
        prior_activities = {e.activity_label for e in state.detected_entities if e.activity_label}
        prior_regions = {e.body_region for e in state.detected_entities if e.body_region}
        prior_alert_keys = {_alert_key(a) for a in state.alerts}
        prior_doc_gap_cpts = {
            t.reason.removeprefix("documentation_gap:")
            for t in state.path_b_triggers
            if t.reason.startswith("documentation_gap:")
        }

        entities, new_suggestions = self._processor.process(state, chunk, now)
        if state.billing_region == "SA" and self._sa_extractor is not None:
            self._merge_sa_detection_insights(state)
        self._reconcile_ncci_alerts(state)
        if self._regional is not None:
            regional_alerts = self._regional.reconcile_chunk(
                state,
                chunk.text,
                set(prior_alert_keys),
            )
            state.alerts.extend(regional_alerts)

        panel = self._insights.build(state, now)
        new_alerts = [a for a in state.alerts if _alert_key(a) not in prior_alert_keys]
        events = self._collect_events(
            state,
            chunk,
            entities,
            new_suggestions,
            new_alerts,
            prior_cpts,
            prior_activities,
            prior_regions,
            session_seen_cpts,
            prior_doc_gap_cpts,
            chunk.text,
        )
        self._append_timeline(state, chunk, entities)

        return PathAResult(
            chunk=chunk,
            entities=entities,
            panel=panel,
            events=events,
            new_alerts=new_alerts,
        )

    def _merge_sa_detection_insights(self, state: SessionState) -> None:
        """Push SBS + ICD-10-AM insight cards (approve/ignore) for SA Path A."""
        assert self._sa_extractor is not None
        sbs_hits = list(self._sa_extractor.last_sbs_hits)
        icd_hits = list(self._sa_extractor.last_icd_hits)
        icd_review_hits = list(self._sa_extractor.last_icd_review_hits)
        if not sbs_hits and not icd_hits and not icd_review_hits:
            return

        catalog = self._sa_extractor.detector.catalog
        approved_icd_codes = [
            i.code
            for i in state.insights
            if i.type == "detected_icd" and i.status == "approved" and i.code
        ]
        auto_icd_codes = [h.code for h in icd_hits]
        all_mapping_icd = list(dict.fromkeys(auto_icd_codes + approved_icd_codes))
        validations = {
            v.sbs_code: v
            for v in validate_sbs_icd_mapping(
                [h.code for h in sbs_hits],
                all_mapping_icd,
                catalog,
            )
        }

        fresh: list[ProtocolInsight] = []
        for hit in sbs_hits:
            validation = validations.get(hit.code)
            validation_status = validation.status if validation else None
            validation_reason = validation.reason if validation else ""
            phrases = ", ".join(hit.matched_phrases) or hit.matched_text
            description = hit.guidance or f"Matched: {phrases}."
            if validation_reason:
                description = f"{description} {validation_reason}".strip()
            fresh.append(
                ProtocolInsight(
                    insight_id=m._insight_id("detected", hit.code),
                    type="detected",
                    label="Detected SBS",
                    question=f"Bill {hit.label} ({hit.code})?",
                    description=description,
                    status="pending",
                    validation_status=validation_status,
                    code=hit.code,
                )
            )

        for hit in icd_hits:
            phrases = ", ".join(hit.matched_phrases) or hit.matched_text
            fresh.append(
                ProtocolInsight(
                    insight_id=m._insight_id("detected_icd", hit.code),
                    type="detected_icd",
                    label="ICD-10-AM",
                    question=f"Accept {hit.label} ({hit.code})?",
                    description=hit.guidance or f"Matched: {phrases}.",
                    status="pending",
                    code=hit.code,
                )
            )

        for hit in icd_review_hits:
            phrases = ", ".join(hit.matched_phrases) or hit.matched_text
            fresh.append(
                ProtocolInsight(
                    insight_id=m._insight_id("detected_icd_review", hit.code),
                    type="detected_icd",
                    label="ICD-10-AM (Review)",
                    question=(
                        f"Confirm {hit.label} ({hit.code})? "
                        f"Clinician review recommended"
                    ),
                    description=(
                        hit.guidance
                        or f"Candidate diagnosis — symptom pattern suggests {hit.code} "
                        f"but diagnosis not confirmed in transcript. Matched: {phrases}."
                    ),
                    status="pending",
                    validation_status="review_recommended",
                    code=hit.code,
                )
            )

        if fresh:
            state.insights = m.merge_insights(state.insights, fresh)

    def _reconcile_ncci_alerts(self, state: SessionState) -> None:
        if not self._enable_ncci:
            return
        segments = self._active_cpt_segments(state)
        fresh_alerts = self._ncci.check_conflicts(state.session_id, segments)
        existing_keys = {
            (tuple(sorted(a.cpt_codes)), a.body_region) for a in state.alerts
        }
        for alert in fresh_alerts:
            key = (tuple(sorted(alert.cpt_codes)), alert.body_region)
            if key in existing_keys:
                continue
            state.alerts.append(alert)
            existing_keys.add(key)
            if len(alert.cpt_codes) != 2:
                continue
            code_a, code_b = sorted(alert.cpt_codes)
            billing_insight = ProtocolInsight(
                insight_id=m._insight_id("billing", f"{code_a}-{code_b}"),
                type="billing",
                label=f"NCCI: {code_a} + {code_b}",
                question=(
                    "Apply Modifier 59?"
                    if "Modifier 59" in alert.message
                    else "Review billing conflict"
                ),
                description=alert.message,
                status="pending",
            )
            state.insights = m.merge_insights(state.insights, [billing_insight])

    @staticmethod
    def _active_cpt_segments(state: SessionState) -> list[tuple[str, str | None]]:
        """All billable CPT + region pairs currently known to Path A."""
        segments: list[tuple[str, str | None]] = [
            (seg.cpt_code, seg.body_region) for seg in state.timer_segments if seg.cpt_code
        ]
        for entity in state.detected_entities:
            if entity.possible_cpt:
                segments.append((entity.possible_cpt, entity.body_region))
        for suggestion in state.suggestions:
            if suggestion.cpt_code:
                segments.append((suggestion.cpt_code, suggestion.body_region))
        return segments

    def _collect_events(
        self,
        state: SessionState,
        chunk: TranscriptChunk,
        entities: list[DetectedEntity],
        new_suggestions: list[Any],
        new_alerts: list[Alert],
        prior_cpts: set[str],
        prior_activities: set[str],
        prior_regions: set[str],
        session_seen_cpts: set[str],
        prior_doc_gap_cpts: set[str],
        chunk_text: str,
    ) -> list[DomainEvent]:
        events: list[DomainEvent] = [
            ChunkProcessed(
                session_id=state.session_id,
                chunk_id=chunk.chunk_id,
                sequence=chunk.sequence,
                entity_count=len(entities),
                suggestion_count=len(new_suggestions),
            )
        ]
        for entity in entities:
            if entity.possible_cpt and entity.possible_cpt not in session_seen_cpts:
                events.append(
                    CptDetected(
                        session_id=state.session_id,
                        cpt_code=entity.possible_cpt,
                        matched_phrase=entity.matched_phrase,
                        body_region=entity.body_region,
                    )
                )
                missing = self._missing_documentation(entity, chunk_text)
                if missing and entity.possible_cpt not in prior_doc_gap_cpts:
                    events.append(
                        DocumentationGapDetected(
                            session_id=state.session_id,
                            cpt_code=entity.possible_cpt,
                            missing_requirements=missing,
                            matched_phrase=entity.matched_phrase,
                        )
                    )
            if entity.activity_label and entity.activity_label not in prior_activities:
                events.append(
                    ActivityChanged(
                        session_id=state.session_id,
                        activity_label=entity.activity_label,
                        cpt_code=entity.possible_cpt,
                        body_region=entity.body_region,
                    )
                )
            if entity.body_region and entity.body_region not in prior_regions:
                events.append(
                    BodyRegionChanged(
                        session_id=state.session_id,
                        body_region=entity.body_region,
                        matched_phrase=entity.matched_phrase,
                        cpt_code=entity.possible_cpt,
                    )
                )
        for alert in new_alerts:
            if alert.alert_type == "ncci_conflict" and len(alert.cpt_codes) >= 2:
                events.append(
                    NcciConflictFound(
                        session_id=state.session_id,
                        cpt_a=alert.cpt_codes[0],
                        cpt_b=alert.cpt_codes[1],
                        severity=alert.severity,
                    )
                )
            if alert.alert_type == "pre_auth_required":
                events.append(
                    PreAuthViolationFound(
                        session_id=state.session_id,
                        policy_id=alert.policy_id or alert.alert_id,
                        message=alert.message,
                        severity=alert.severity,
                    )
                )
            if alert.alert_type == "billing_conflict":
                events.append(
                    CodeConflictFound(
                        session_id=state.session_id,
                        rule_id=alert.rule_id or alert.alert_id,
                        message=alert.message,
                        severity=alert.severity,
                    )
                )
            if (
                alert.severity == "high"
                or alert.alert_type in {"ncci_conflict", "pre_auth_required", "billing_conflict"}
            ):
                events.append(
                    PathAAlertRaised(
                        session_id=state.session_id,
                        alert_id=alert.alert_id,
                        alert_type=alert.alert_type,
                        severity=alert.severity,
                        message=alert.message,
                        cpt_codes=list(alert.cpt_codes),
                    )
                )
        return events

    def _missing_documentation(self, entity: DetectedEntity, chunk_text: str) -> list[str]:
        if not entity.possible_cpt:
            return []
        meta = self._meta.get(entity.possible_cpt)
        if not meta:
            return []
        requirements = list(meta.get("documentation_requirements") or [])
        if not requirements:
            return []
        lower = chunk_text.lower()
        missing: list[str] = []
        for requirement in requirements:
            tokens = [token for token in requirement.lower().split() if len(token) > 4]
            if not tokens:
                missing.append(requirement)
                continue
            if not any(token in lower for token in tokens[:3]):
                missing.append(requirement)
        return missing

    @staticmethod
    def _append_timeline(
        state: SessionState,
        chunk: TranscriptChunk,
        entities: list[DetectedEntity],
    ) -> None:
        state.timeline_events.append(
            TimelineEvent(
                event_id=str(uuid.uuid4()),
                session_id=state.session_id,
                kind="chunk",
                summary=chunk.text[:120],
                chunk_id=chunk.chunk_id,
            )
        )
        for entity in entities:
            if entity.possible_cpt:
                state.timeline_events.append(
                    TimelineEvent(
                        event_id=str(uuid.uuid4()),
                        session_id=state.session_id,
                        kind="cpt_detected",
                        summary=f"{entity.matched_phrase} → {entity.possible_cpt}",
                        chunk_id=chunk.chunk_id,
                        cpt_code=entity.possible_cpt,
                    )
                )
