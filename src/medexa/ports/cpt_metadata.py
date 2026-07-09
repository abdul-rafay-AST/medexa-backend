from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CptMetadataPort(Protocol):
    """Port for CPT display metadata — satisfied by legacy and hybrid loaders."""

    def get(self, cpt_code: str) -> dict[str, Any] | None: ...

    def is_timed(self, cpt_code: str) -> bool: ...

    def get_display_name(self, cpt_code: str) -> str: ...
