from __future__ import annotations

from typing import Protocol

from medexa.schemas import SessionState


class PreAuthViolation:
    __slots__ = ("policy_id", "severity", "message", "service_category")

    def __init__(
        self,
        policy_id: str,
        severity: str,
        message: str,
        service_category: str | None = None,
    ) -> None:
        self.policy_id = policy_id
        self.severity = severity
        self.message = message
        self.service_category = service_category


class SessionFieldViolation:
    __slots__ = ("field_name", "severity", "message")

    def __init__(self, field_name: str, severity: str, message: str) -> None:
        self.field_name = field_name
        self.severity = severity
        self.message = message


class PreAuthValidatorPort(Protocol):
    def validate_session_fields(self, state: SessionState) -> list[SessionFieldViolation]: ...

    def validate_pre_auth(self, state: SessionState) -> list[PreAuthViolation]: ...


class PreAuthExchangePort(Protocol):
    def check_eligibility(self, state: SessionState) -> dict[str, object]: ...

    def submit_prior_auth(self, state: SessionState, payload: dict[str, object]) -> dict[str, object]: ...
