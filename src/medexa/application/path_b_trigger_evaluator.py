"""Path B trigger policy — clinical-first, config-driven, sparse LLM calls.

Design goals:
  * Fire on clinically meaningful moments (pain, body region, gaps, safety) —
    do NOT wait for CPT billing detection.
  * CPT detections are optional / low-priority context, never the gate.
  * Declarative rules in ``config/trigger_rules.json``.
  * Per-rule fire caps + cooldowns; optional once-per-match keys (e.g. each body region).
  * Global session debounce so Path B cannot spam Bedrock while chatting.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

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
    PathBTriggerRequested,
    PreAuthViolationFound,
)

_EVENT_TYPE_MAP: dict[str, type] = {
    "body_region_changed": BodyRegionChanged,
    "activity_changed": ActivityChanged,
    "ncci_conflict_found": NcciConflictFound,
    "pre_auth_violation_found": PreAuthViolationFound,
    "code_conflict_found": CodeConflictFound,
    "documentation_gap_detected": DocumentationGapDetected,
    "path_a_alert_raised": PathAAlertRaised,
    "chunk_processed": ChunkProcessed,
    "cpt_detected": CptDetected,
}

# Clinical intent ranks higher than billing CPT — CPT must never block narrative Path B.
_PRIORITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "billing": 4,  # CPT / milestones last
}


@dataclass(frozen=True)
class TriggerRule:
    """One declarative trigger rule loaded from JSON config."""

    id: str
    description: str
    priority: str
    max_fires_per_session: int
    cooldown_seconds: int
    event_type: str | None = None
    match_mode: str | None = None  # "keywords" | "time_milestone" | "interval" | None
    keywords: tuple[str, ...] = ()
    condition: str | None = None
    severity_filter: tuple[str, ...] = ()
    milestone_minutes: int | None = None
    interval_seconds: int | None = None
    once_per_match: bool = False

    @staticmethod
    def from_dict(data: dict[str, Any]) -> TriggerRule:
        return TriggerRule(
            id=data["id"],
            description=data.get("description", ""),
            priority=data.get("priority", "medium"),
            max_fires_per_session=int(data.get("max_fires_per_session", 1)),
            cooldown_seconds=int(data.get("cooldown_seconds", 30)),
            event_type=data.get("event_type"),
            match_mode=data.get("match_mode"),
            keywords=tuple(data.get("keywords", ())),
            condition=data.get("condition"),
            severity_filter=tuple(data.get("severity_filter", ())),
            milestone_minutes=data.get("milestone_minutes"),
            interval_seconds=data.get("interval_seconds"),
            once_per_match=bool(data.get("once_per_match", False)),
        )


@dataclass(frozen=True)
class TriggerDecision:
    reason: str
    source_event_type: str
    critical: bool = False
    rule_id: str = ""


@dataclass
class _RuleClock:
    fire_count: int = 0
    last_fired_at: datetime | None = None
    last_fired_elapsed: float = -1.0


@dataclass
class _SessionClock:
    rule_clocks: dict[str, _RuleClock] = field(default_factory=dict)
    seen_cpt_codes: set[str] = field(default_factory=set)
    last_chunk_sequence: int = -1
    milestone_fired: set[int] = field(default_factory=set)
    fired_match_keys: set[str] = field(default_factory=set)
    last_any_fire_at: datetime | None = None
    last_any_fire_elapsed: float = -1.0


def load_trigger_rules(config_dir: Path | None = None) -> list[TriggerRule]:
    """Load trigger rules from ``config/trigger_rules.json``."""
    paths_to_try: list[Path] = []
    if config_dir is not None:
        paths_to_try.append(Path(config_dir) / "trigger_rules.json")
    paths_to_try.append(Path("config") / "trigger_rules.json")

    for path in paths_to_try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return [TriggerRule.from_dict(rule) for rule in data.get("triggers", [])]
    return _default_rules()


def _default_rules() -> list[TriggerRule]:
    return [
        TriggerRule(
            id="body_region_transition",
            description="Body region changed",
            event_type="body_region_changed",
            max_fires_per_session=6,
            cooldown_seconds=12,
            priority="high",
        ),
        TriggerRule(
            id="documentation_gap_first",
            description="Documentation gap",
            event_type="documentation_gap_detected",
            max_fires_per_session=4,
            cooldown_seconds=20,
            priority="high",
        ),
        TriggerRule(
            id="activity_transition",
            description="Activity changed",
            event_type="activity_changed",
            max_fires_per_session=4,
            cooldown_seconds=20,
            priority="high",
        ),
        TriggerRule(
            id="ncci_conflict",
            description="NCCI conflict",
            event_type="ncci_conflict_found",
            severity_filter=("high", "medium"),
            max_fires_per_session=3,
            cooldown_seconds=20,
            priority="critical",
        ),
    ]


class PathBTriggerEvaluator:
    """Decide whether a Path A event batch warrants one Bedrock Path B call."""

    def __init__(
        self,
        interval_seconds: int,
        *,
        rules: list[TriggerRule] | None = None,
        config_dir: Path | None = None,
        critical_cooldown_seconds: int | None = None,
        global_debounce_seconds: int | None = None,
    ) -> None:
        self._rules = rules or load_trigger_rules(config_dir)
        self._rules.sort(key=lambda r: _PRIORITY_ORDER.get(r.priority, 2))
        self._sessions: dict[str, _SessionClock] = {}
        # Floor for critical rules only.
        self._critical_cooldown = max(
            critical_cooldown_seconds if critical_cooldown_seconds is not None else 12,
            8,
        )
        # Short global gap between ANY Path B fires (prevents double Bedrock calls).
        self._global_debounce = max(
            global_debounce_seconds
            if global_debounce_seconds is not None
            else min(interval_seconds, 12),
            6,
        )

    @property
    def rules(self) -> list[TriggerRule]:
        return list(self._rules)

    def evaluate_batch(
        self,
        events: list[DomainEvent],
        *,
        now: datetime,
        chunk_text: str | None = None,
        elapsed_seconds: float = 0.0,
    ) -> TriggerDecision | None:
        if not events and not (chunk_text and chunk_text.strip()):
            return None
        session_id = events[0].session_id if events else ""
        if not session_id:
            return None
        clock = self._clock(session_id)

        chunk = next((e for e in events if isinstance(e, ChunkProcessed)), None)
        if chunk is not None:
            if chunk.sequence == clock.last_chunk_sequence:
                return None
            clock.last_chunk_sequence = chunk.sequence

        # Track new CPT codes for optional billing-context rules (never a gate).
        for event in events:
            if isinstance(event, CptDetected):
                clock.seen_cpt_codes.add(event.cpt_code)

        if clock.last_any_fire_at is not None:
            # Prefer using elapsed_seconds (crucial for Simulator tests where real time doesn't advance)
            if elapsed_seconds > 0 and clock.last_any_fire_elapsed >= 0:
                since = elapsed_seconds - clock.last_any_fire_elapsed
            else:
                since = (now - clock.last_any_fire_at).total_seconds()
            
            if since < self._global_debounce:
                # Still allow critical safety during debounce.
                critical_only = [r for r in self._rules if r.priority == "critical"]
                for rule in critical_only:
                    decision = self._evaluate_rule(
                        rule, events, clock, now, chunk_text, elapsed_seconds
                    )
                    if decision is not None:
                        self._mark_fired(session_id, rule, now, decision, elapsed_seconds)
                        return decision
                return None

        for rule in self._rules:
            decision = self._evaluate_rule(rule, events, clock, now, chunk_text, elapsed_seconds)
            if decision is not None:
                self._mark_fired(session_id, rule, now, decision, elapsed_seconds)
                return decision
        return None

    def _evaluate_rule(
        self,
        rule: TriggerRule,
        events: list[DomainEvent],
        clock: _SessionClock,
        now: datetime,
        chunk_text: str | None,
        elapsed_seconds: float,
    ) -> TriggerDecision | None:
        if not self._can_fire(clock, rule, now):
            return None

        # Keyword / clinical narrative — evaluate even when an event_type is also set.
        if rule.match_mode == "keywords":
            return self._match_keywords(rule, clock, chunk_text)

        if rule.match_mode == "time_milestone" and rule.milestone_minutes is not None:
            milestone_sec = rule.milestone_minutes * 60
            if (
                elapsed_seconds >= milestone_sec
                and rule.milestone_minutes not in clock.milestone_fired
            ):
                clock.milestone_fired.add(rule.milestone_minutes)
                return TriggerDecision(
                    reason=f"{rule.id}:{rule.milestone_minutes}m",
                    source_event_type="timer_milestone",
                    critical=False,
                    rule_id=rule.id,
                )
            return None

        if rule.match_mode == "interval" and rule.interval_seconds is not None:
            if elapsed_seconds >= rule.interval_seconds:
                return TriggerDecision(
                    reason=rule.id,
                    source_event_type="interval",
                    critical=False,
                    rule_id=rule.id,
                )
            return None

        if rule.event_type:
            return self._match_event(rule, events, clock)

        return None

    def _match_keywords(
        self,
        rule: TriggerRule,
        clock: _SessionClock,
        chunk_text: str | None,
    ) -> TriggerDecision | None:
        if not chunk_text or not rule.keywords:
            return None
        lower = chunk_text.lower()
        # Prefer longer phrases first so "out of ten" beats "ten".
        sorted_keywords = sorted(rule.keywords, key=len, reverse=True)
        matched: str | None = None
        for keyword in sorted_keywords:
            needle = keyword.lower().strip()
            if not needle:
                continue
            if " " in needle or "/" in needle or any(ch.isdigit() for ch in needle):
                if needle in lower:
                    matched = keyword
                    break
            else:
                if re.search(rf"\b{re.escape(needle)}\b", lower):
                    matched = keyword
                    break
        if matched is None:
            return None

        match_key = f"{rule.id}:{matched.lower()}"
        if rule.once_per_match and match_key in clock.fired_match_keys:
            return None

        return TriggerDecision(
            reason=f"{rule.id}:{matched}",
            source_event_type="chunk_processed",
            critical=rule.priority == "critical",
            rule_id=rule.id,
        )

    def _match_event(
        self,
        rule: TriggerRule,
        events: list[DomainEvent],
        clock: _SessionClock,
    ) -> TriggerDecision | None:
        event_cls = _EVENT_TYPE_MAP.get(rule.event_type or "")
        if event_cls is None:
            return None

        matched_event: DomainEvent | None = None
        for event in events:
            if not isinstance(event, event_cls):
                continue
            if rule.severity_filter:
                severity = getattr(event, "severity", None)
                if severity not in rule.severity_filter:
                    continue
            if rule.condition == "has_new_cpt":
                if isinstance(event, ChunkProcessed) and event.suggestion_count <= 0:
                    continue
            if rule.once_per_match:
                detail = _event_detail(event) or event.event_type
                match_key = f"{rule.id}:{detail.lower()}"
                if match_key in clock.fired_match_keys:
                    continue
            matched_event = event
            break

        if matched_event is None:
            return None
        return TriggerDecision(
            reason=f"{rule.id}:{_event_detail(matched_event)}",
            source_event_type=matched_event.event_type,
            critical=rule.priority == "critical",
            rule_id=rule.id,
        )

    def _can_fire(self, clock: _SessionClock, rule: TriggerRule, now: datetime) -> bool:
        rc = clock.rule_clocks.get(rule.id)
        if rc is None:
            return True
        if rc.fire_count >= rule.max_fires_per_session:
            return False
        cooldown = self._critical_cooldown if rule.priority == "critical" else rule.cooldown_seconds
        
        # Prefer using elapsed_seconds for cooldowns if available
        if elapsed_seconds > 0 and rc.last_fired_elapsed >= 0:
            since = elapsed_seconds - rc.last_fired_elapsed
            if since < cooldown:
                return False
        elif rc.last_fired_at is not None:
            since = (now - rc.last_fired_at).total_seconds()
            if since < cooldown:
                return False
        return True

    def _mark_fired(
        self, session_id: str, rule: TriggerRule, now: datetime, decision: TriggerDecision, elapsed_seconds: float = 0.0
    ) -> None:
        clock = self._clock(session_id)
        rc = clock.rule_clocks.get(rule.id)
        if rc is None:
            rc = _RuleClock()
            clock.rule_clocks[rule.id] = rc
        rc.fire_count += 1
        rc.last_fired_at = now
        rc.last_fired_elapsed = elapsed_seconds
        clock.last_any_fire_at = now
        clock.last_any_fire_elapsed = elapsed_seconds
        if rule.once_per_match:
            # reason is "{rule_id}:{detail}"
            detail = decision.reason.split(":", 1)[-1].lower()
            clock.fired_match_keys.add(f"{rule.id}:{detail}")

    def build_trigger_event(self, session_id: str, decision: TriggerDecision) -> PathBTriggerRequested:
        return PathBTriggerRequested(
            session_id=session_id,
            trigger_id=str(uuid.uuid4()),
            reason=decision.reason,
            source_event_type=decision.source_event_type,
        )

    def _clock(self, session_id: str) -> _SessionClock:
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionClock()
        return self._sessions[session_id]

    def reset_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def register_cpt(self, session_id: str, cpt_code: str) -> bool:
        clock = self._clock(session_id)
        if cpt_code in clock.seen_cpt_codes:
            return False
        clock.seen_cpt_codes.add(cpt_code)
        return True


def _event_detail(event: DomainEvent) -> str:
    if isinstance(event, BodyRegionChanged):
        return event.body_region
    if isinstance(event, ActivityChanged):
        return event.activity_label
    if isinstance(event, CptDetected):
        return event.cpt_code
    if isinstance(event, NcciConflictFound):
        return f"{event.cpt_a}+{event.cpt_b}"
    if isinstance(event, PreAuthViolationFound):
        return event.policy_id
    if isinstance(event, CodeConflictFound):
        return event.rule_id
    if isinstance(event, DocumentationGapDetected):
        return event.cpt_code
    if isinstance(event, PathAAlertRaised):
        return event.alert_type
    if isinstance(event, ChunkProcessed):
        return f"suggestions={event.suggestion_count}"
    return ""
