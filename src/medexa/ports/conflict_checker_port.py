from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from medexa.schemas import SessionState


@dataclass(frozen=True)
class ConflictFinding:
    rule_id: str
    severity: str
    message: str
    service_category: str | None = None


class RegionalConflictCheckerPort(Protocol):
    def evaluate(self, state: SessionState) -> list[ConflictFinding]: ...

    def evaluate_transcript(self, state: SessionState, text: str) -> list[ConflictFinding]: ...
