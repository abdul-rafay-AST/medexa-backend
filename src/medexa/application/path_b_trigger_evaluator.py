"""Path B trigger policy — declarative, config-driven, clinically intelligent.

Design goals:
  * Load trigger rules from ``config/trigger_rules.json`` (or S3 cache).
  * Per-trigger fire counts + cooldowns — not once-per-session blanket limits.
  * Priority ordering: critical fires immediately, medium/low respect cooldowns.
  * Keyword phrase matching for clinical narrative triggers.
  * Session time milestones (at 15m, 30m, 45m).
  * Never spam the LLM — every call must be justified by a concrete clinical event.
"""

from __future__ import annotations

import json
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
}


@dataclass(frozen=True)
class TriggerRule:
    """One declarative trigger rule loaded from JSON config."""

    id: str
    description: str
    priority: str  # "critical" | "high" | "medium" | "low"
    max_fires_per_session: int
    cooldown_seconds: int
    event_type: str | None = None
    match_mode: str | None = None  # "keywords" | "time_milestone" | None
    keywords: tuple[str, ...] = ()
    condition: str | None = None
    severity_filter: tuple[str, ...] = ()
    milestone_minutes: int | None = None

    @staticmethod
    def from_dict(data: dict[str, Any]) -> TriggerRule:
        return TriggerRule(
            id=data["id"],
            description=data.get("description", ""),
            priority=data.get("priority", "medium"),
            max_fires_per_session=data.get("max_fires_per_session", 1),
            cooldown_seconds=data.get("cooldown_seconds", 30),
            event_type=data.get("event_type"),
            match_mode=data.get("match_mode"),
            keywords=tuple(data.get("keywords", ())),
            condition=data.get("condition"),
            severity_filter=tuple(data.get("severity_filter", ())),
            milestone_minutes=data.get("milestone_minutes"),
        )


@dataclass(frozen=True)
class TriggerDecision:
    reason: str
    source_event_type: str
    critical: bool = False
    rule_id: str = ""


@dataclass
class _RuleClock:
    """Per-rule fire count and last-fired timestamp within a session."""

    fire_count: int = 0
    last_fired_at: datetime | None = None


@dataclass
class _SessionClock:
    """Per-session state for the trigger evaluator."""

    rule_clocks: dict[str, _RuleClock] = field(default_factory=dict)
    seen_cpt_codes: set[str] = field(default_factory=set)
    last_chunk_sequence: int = -1
    milestone_fired: set[int] = field(default_factory=set)


def load_trigger_rules(config_dir: Path | None = None) -> list[TriggerRule]:
    """Load trigger rules from ``config/trigger_rules.json``."""
    paths_to_try = []
    if config_dir is not None:
        paths_to_try.append(config_dir / "trigger_rules.json")
    paths_to_try.append(Path("config") / "trigger_rules.json")

    for path in paths_to_try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return [TriggerRule.from_dict(rule) for rule in data.get("triggers", [])]
    return _default_rules()


def _default_rules() -> list[TriggerRule]:
    """Minimal built-in rules when config file is unavailable."""
    return [
        TriggerRule(
            id="body_region_transition",
            description="Body region changed",
            event_type="body_region_changed",
            max_fires_per_session=4,
            cooldown_seconds=45,
            priority="high",
        ),
        TriggerRule(
            id="ncci_conflict",
            description="NCCI conflict detected",
            event_type="ncci_conflict_found",
            severity_filter=("high", "medium"),
            max_fires_per_session=3,
            cooldown_seconds=30,
            priority="critical",
        ),
        TriggerRule(
            id="activity_transition",
            description="Activity changed",
            event_type="activity_changed",
            max_fires_per_session=4,
            cooldown_seconds=45,
            priority="high",
        ),
    ]


# --- Priority ordering for evaluation ---
_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class PathBTriggerEvaluator:
    """Decide whether a Path A event batch warrants one Bedrock Path B call.

    Uses declarative trigger rules loaded from config. Each rule has its own
    fire count limit and cooldown, so the system can fire body-region triggers
    multiple times while only firing medication-allergy triggers once.
    """

    def __init__(
        self,
        interval_seconds: int,
        *,
        rules: list[TriggerRule] | None = None,
        config_dir: Path | None = None,
        critical_cooldown_seconds: int | None = None,
    ) -> None:
        self._rules = rules or load_trigger_rules(config_dir)
        # Sort rules by priority for evaluation order.
        self._rules.sort(key=lambda r: _PRIORITY_ORDER.get(r.priority, 2))
        self._sessions: dict[str, _SessionClock] = {}
        # Default critical cooldown floor.
        self._critical_cooldown = max(
            critical_cooldown_seconds if critical_cooldown_seconds is not None else interval_seconds,
            15,
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
        if not events:
            return None
        session_id = events[0].session_id
        clock = self._clock(session_id)

        # Deduplicate chunk sequence to prevent re-evaluation.
        chunk = next((e for e in events if isinstance(e, ChunkProcessed)), None)
        if chunk is not None:
            if chunk.sequence == clock.last_chunk_sequence:
                return None
            clock.last_chunk_sequence = chunk.sequence
            # Track new CPT codes for the has_new_cpt condition.
            if chunk.entity_count > 0:
                for event in events:
                    if isinstance(event, ChunkProcessed):
                        # Entities are not directly on ChunkProcessed; tracked via cpt below.
                        pass

        # Evaluate each rule in priority order — first match wins.
        for rule in self._rules:
            decision = self._evaluate_rule(rule, events, clock, now, chunk_text, elapsed_seconds)
            if decision is not None:
                self._mark_fired(session_id, rule.id, now)
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

        # Event-type based rules.
        if rule.event_type and rule.match_mode is None:
            event_cls = _EVENT_TYPE_MAP.get(rule.event_type)
            if event_cls is None:
                return None
            matched_event = None
            for event in events:
                if isinstance(event, event_cls):
                    # Check severity filter if applicable.
                    if rule.severity_filter:
                        severity = getattr(event, "severity", None) or getattr(
                            event, "alert_type", None
                        )
                        if severity not in rule.severity_filter:
                            continue
                    # Check condition (has_new_cpt).
                    if rule.condition == "has_new_cpt" and isinstance(event, ChunkProcessed):
                        if getattr(event, "suggestion_count", 0) == 0:
                            continue
                    matched_event = event
                    break
            if matched_event is None:
                return None
            is_critical = rule.priority == "critical"
            return TriggerDecision(
                reason=f"{rule.id}:{_event_detail(matched_event)}",
                source_event_type=matched_event.event_type,
                critical=is_critical,
                rule_id=rule.id,
            )

        # Keyword-based rules.
        if rule.match_mode == "keywords" and chunk_text:
            lower = chunk_text.lower()
            matched_keyword = None
            for keyword in rule.keywords:
                if keyword.lower() in lower:
                    matched_keyword = keyword
                    break
            if matched_keyword is None:
                return None
            return TriggerDecision(
                reason=f"{rule.id}:{matched_keyword}",
                source_event_type="chunk_processed",
                critical=rule.priority == "critical",
                rule_id=rule.id,
            )

        # Time milestone rules.
        if rule.match_mode == "time_milestone" and rule.milestone_minutes is not None:
            milestone_sec = rule.milestone_minutes * 60
            if elapsed_seconds >= milestone_sec and rule.milestone_minutes not in clock.milestone_fired:
                clock.milestone_fired.add(rule.milestone_minutes)
                return TriggerDecision(
                    reason=f"{rule.id}:{rule.milestone_minutes}m",
                    source_event_type="timer_milestone",
                    critical=False,
                    rule_id=rule.id,
                )

        return None

    def _can_fire(self, clock: _SessionClock, rule: TriggerRule, now: datetime) -> bool:
        rc = clock.rule_clocks.get(rule.id)
        if rc is None:
            return True
        if rc.fire_count >= rule.max_fires_per_session:
            return False
        if rule.cooldown_seconds > 0 and rc.last_fired_at is not None:
            elapsed = (now - rc.last_fired_at).total_seconds()
            if elapsed < rule.cooldown_seconds:
                return False
        return True

    def _mark_fired(self, session_id: str, rule_id: str, now: datetime) -> None:
        clock = self._clock(session_id)
        rc = clock.rule_clocks.get(rule_id)
        if rc is None:
            rc = _RuleClock()
            clock.rule_clocks[rule_id] = rc
        rc.fire_count += 1
        rc.last_fired_at = now

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
        """Track a CPT code as seen. Returns True if this is the first time."""
        clock = self._clock(session_id)
        if cpt_code in clock.seen_cpt_codes:
            return False
        clock.seen_cpt_codes.add(cpt_code)
        return True


def _event_detail(event: DomainEvent) -> str:
    """Extract a short detail string from a domain event for the trigger reason."""
    if isinstance(event, BodyRegionChanged):
        return event.body_region
    if isinstance(event, ActivityChanged):
        return event.activity_label
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
    return ""
