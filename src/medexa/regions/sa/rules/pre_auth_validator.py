from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from medexa.ports.conflict_checker_port import ConflictFinding
from medexa.ports.pre_auth import PreAuthViolation, SessionFieldViolation
from medexa.regions.bundle import RegionBundle
from medexa.regions.policy_loader import load_activity_synonyms, load_policy_records
from medexa.regions.sa.loaders.policy_loaders import (
    SaudiPreAuthServicesLoader,
    SaudiRequiredSessionFieldsLoader,
)
from medexa.schemas import SessionState


def _is_blank(value: str | None) -> bool:
    return value is None or not str(value).strip()


@dataclass
class SaudiPreAuthValidator:
    bundle: RegionBundle

    def __post_init__(self) -> None:
        self._session_fields = SaudiRequiredSessionFieldsLoader(self.bundle).load()
        self._pre_auth_services = SaudiPreAuthServicesLoader(self.bundle).load()

    def validate_session_fields(self, state: SessionState) -> list[SessionFieldViolation]:
        violations: list[SessionFieldViolation] = []
        required_fields = self._session_fields.get("required_fields", [])
        for field_name in required_fields:
            if _is_blank(getattr(state, field_name, None)):
                violations.append(
                    SessionFieldViolation(
                        field_name=str(field_name),
                        severity="error",
                        message=f"Saudi session is missing required field: {field_name}",
                    )
                )
        if state.billing_region == "SA" and _is_blank(state.payer_id):
            violations.append(
                SessionFieldViolation(
                    field_name="payer_id",
                    severity="error",
                    message="Saudi sessions require payer_id for NPHIES routing.",
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
                policy_id="SA-PREAUTH-SESSION",
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
class SaudiConflictChecker:
    bundle: RegionBundle

    def __post_init__(self) -> None:
        self._rules = load_policy_records(self.bundle.asset_path("rules/diagnosis_procedure_rules.json"))
        self._synonyms = load_activity_synonyms(self.bundle.asset_path("codes/activity_synonyms.json"))

    def evaluate(self, state: SessionState) -> list[ConflictFinding]:
        findings: list[ConflictFinding] = []
        if not state.timer_segments:
            findings.append(
                ConflictFinding(
                    rule_id="SA-DX-001",
                    severity="warning",
                    message="No billable services captured yet for this Saudi encounter.",
                )
            )
        if state.billing_region == "SA" and not state.payer_id:
            findings.append(
                ConflictFinding(
                    rule_id="SA-CLAIM-001",
                    severity="error",
                    message="Payer identity is required before Saudi claim exchange.",
                )
            )
        return findings

    def evaluate_transcript(self, state: SessionState, text: str) -> list[ConflictFinding]:
        lowered = text.lower()
        findings: list[ConflictFinding] = []
        categories = {
            category
            for phrase, category in self._synonyms.items()
            if phrase in lowered
        }
        if "advanced_imaging" in categories and not state.pre_auth_reference:
            findings.append(
                ConflictFinding(
                    rule_id="SA-PREAUTH-IMAGING",
                    severity="high",
                    message="Advanced imaging mentioned without a pre-authorization reference on file.",
                    service_category="advanced_imaging",
                )
            )
        if "inpatient_admission" in categories and not state.pre_auth_reference:
            findings.append(
                ConflictFinding(
                    rule_id="SA-PREAUTH-INPATIENT",
                    severity="high",
                    message="Inpatient admission mentioned without a pre-authorization reference on file.",
                    service_category="inpatient_admission",
                )
            )
        return findings


@dataclass
class SaudiEncounterBillingEngine:
    bundle: RegionBundle

    def units_for_segment(self, accumulated_seconds: int) -> int:
        if accumulated_seconds <= 0:
            return 0
        return 1


@dataclass
class SaudiDocumentationGapChecker:
    bundle: RegionBundle

    def __post_init__(self) -> None:
        self._requirements = load_policy_records(
            self.bundle.asset_path("rules/documentation_requirements.json")
        )

    def missing_for_category(self, service_category: str, documented_elements: set[str]) -> list[str]:
        for item in self._requirements:
            if item.get("service_category") != service_category:
                continue
            required = {str(value) for value in item.get("required_elements", [])}
            return sorted(required - documented_elements)
        return []
