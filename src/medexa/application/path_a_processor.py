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
    ) -> None:
        self._processor = transcript_processor
        self._insights = insights_builder
        self._ncci = ncci_checker
        self._meta = metadata
        self._timers = timer_engine
        self._enable_ncci = enable_ncci
        self._regional = regional_path_a

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

        entities, new_suggestions = self._processor.process(state, chunk, now)
        self._refresh_rules_insights(state)
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

    def _refresh_rules_insights(self, state: SessionState) -> None:
        fresh: list[ProtocolInsight] = []
        for suggestion in state.suggestions:
            if suggestion.status in ("dismissed", "applied", "expired") or not suggestion.cpt_code:
                continue
            key = f"{suggestion.cpt_code}:{suggestion.body_region or ''}"
            display = self._meta.get_display_name(suggestion.cpt_code)
            fresh.append(
                ProtocolInsight(
                    insight_id=m._insight_id("detected", key),
                    type="detected",
                    label=display,
                    question=f"Bill {display} ({suggestion.cpt_code})?",
                    description=suggestion.message,
                )
            )
        non_detected = [i for i in state.insights if i.type != "detected"]
        state.insights = m.merge_insights(non_detected, fresh)

    def _reconcile_ncci_alerts(self, state: SessionState) -> None:
        if not self._enable_ncci:
            return
        active_codes = list({seg.cpt_code for seg in state.timer_segments if seg.stop_time is None})
        active_codes += [s.cpt_code for s in state.suggestions if s.status == "applied" and s.cpt_code]
        unique = sorted(set(active_codes))
        for i, code_a in enumerate(unique):
            for code_b in unique[i + 1 :]:
                rule = self._ncci.check_conflict(code_a, code_b)
                if not rule:
                    continue
                key = f"{code_a}-{code_b}"
                if any(a.alert_type == "ncci_conflict" and key in a.message for a in state.alerts):
                    continue
                billing_insight = ProtocolInsight(
                    insight_id=m._insight_id("billing", f"{code_a}-{code_b}"),
                    type="billing",
                    label=f"NCCI: {code_a} + {code_b}",
                    question="Apply Modifier 59?" if rule["modifier_59_possible"] else "Review billing conflict",
                    description=rule["explanation"],
                )
                state.insights = m.merge_insights(state.insights, [billing_insight])
                
                state.alerts.append(
                    Alert(
                        alert_id=str(uuid.uuid4()),
                        alert_type="ncci_conflict",
                        severity="warning",
                        message=f"NCCI conflict {key}: {rule['explanation']}",
                        cpt_codes={code_a, code_b},
                    )
                )

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
                if missing:
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
