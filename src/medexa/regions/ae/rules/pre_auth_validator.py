from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from medexa.ports.conflict_checker_port import ConflictFinding
from medexa.ports.pre_auth import PreAuthViolation, SessionFieldViolation
from medexa.regions.ae.loaders.policy_loaders import (
    UaePreAuthServicesLoader,
    UaeRequiredSessionFieldsLoader,
)
from medexa.regions.ae.rules.emirate_rules_resolver import UaeEmirateRulesResolver
from medexa.regions.bundle import RegionBundle
from medexa.regions.policy_loader import load_activity_synonyms, load_policy_records
from medexa.schemas import SessionState


def _is_blank(value: str | None) -> bool:
    return value is None or not str(value).strip()


@dataclass
class UaePreAuthValidator:
    bundle: RegionBundle

    def __post_init__(self) -> None:
        self._session_fields = UaeRequiredSessionFieldsLoader(self.bundle).load()
        self._pre_auth_services = UaePreAuthServicesLoader(self.bundle).load()
        self._emirate_resolver = UaeEmirateRulesResolver(self.bundle)

    def validate_session_fields(self, state: SessionState) -> list[SessionFieldViolation]:
        violations: list[SessionFieldViolation] = []
        required_fields = self._session_fields.get("required_fields", [])
        for field_name in required_fields:
            if _is_blank(getattr(state, field_name, None)):
                violations.append(
                    SessionFieldViolation(
                        field_name=str(field_name),
                        severity="error",
                        message=f"UAE session is missing required field: {field_name}",
                    )
                )
        if state.emirate and self._emirate_resolver.resolve(state.emirate) is None:
            violations.append(
                SessionFieldViolation(
                    field_name="emirate",
                    severity="error",
                    message=f"Unsupported UAE emirate routing profile: {state.emirate}",
                )
            )
        return violations

    def validate_pre_auth(self, state: SessionState) -> list[PreAuthViolation]:
        if not self.bundle.profile.pre_authorization_required:
            return []
        if not _is_blank(state.pre_auth_reference):
            return []
        return [
            PreAuthViolation(
                policy_id="AE-PREAUTH-SESSION",
                severity="warning",
                message="No pre-authorization reference supplied at session start.",
            )
        ]

    def check_transcript_text(self, text: str) -> list[PreAuthViolation]:
        lowered = text.lower()
        violations: list[PreAuthViolation] = []
        for rule in self._pre_auth_services:
            if not rule.get("requires_pre_auth"):
                continue
            keywords = [str(keyword).lower() for keyword in rule.get("keywords", [])]
            if any(keyword in lowered for keyword in keywords):
                violations.append(
                    PreAuthViolation(
                        policy_id=str(rule.get("service_category", "unknown")),
                        severity=str(rule.get("severity", "medium")),
                        message=str(rule.get("message", "Prior authorization may be required.")),
                        service_category=str(rule.get("service_category", "")),
                    )
                )
        return violations


@dataclass
class UaeConflictChecker:
    bundle: RegionBundle

    def __post_init__(self) -> None:
        self._rules = load_policy_records(self.bundle.asset_path("rules/diagnosis_procedure_rules.json"))
        self._emirate_edits = load_policy_records(
            self.bundle.asset_path("rules/emirate_specific_edits.json")
        )
        self._synonyms = load_activity_synonyms(self.bundle.asset_path("codes/activity_synonyms.json"))

    def evaluate(self, state: SessionState) -> list[ConflictFinding]:
        findings: list[ConflictFinding] = []
        if state.emirate:
            for edit in self._emirate_edits:
                if edit.get("emirate") == state.emirate:
                    findings.append(
                        ConflictFinding(
                            rule_id=str(edit.get("edit_id", "AE-EDIT")),
                            severity=str(edit.get("severity", "warning")),
                            message=str(edit.get("description", "")),
                        )
                    )
        if not state.timer_segments:
            findings.append(
                ConflictFinding(
                    rule_id="AE-DX-001",
                    severity="warning",
                    message="No billable services captured yet for this UAE encounter.",
                )
            )
        if not state.emirate:
            findings.append(
                ConflictFinding(
                    rule_id="AE-CLAIM-001",
                    severity="error",
                    message="UAE sessions require emirate routing before claim exchange.",
                )
            )
        return findings

    def evaluate_transcript(self, state: SessionState, text: str) -> list[ConflictFinding]:
        lowered = text.lower()
        categories = {
            category
            for phrase, category in self._synonyms.items()
            if phrase in lowered
        }
        findings: list[ConflictFinding] = []
        if "advanced_imaging" in categories and not state.pre_auth_reference:
            findings.append(
                ConflictFinding(
                    rule_id="AE-PREAUTH-IMAGING",
                    severity="high",
                    message="Advanced imaging mentioned without a pre-authorization reference on file.",
                    service_category="advanced_imaging",
                )
            )
        return findings


@dataclass
class UaeEncounterBillingEngine:
    bundle: RegionBundle

    def units_for_segment(self, accumulated_seconds: int) -> int:
        if accumulated_seconds <= 0:
            return 0
        return 1
