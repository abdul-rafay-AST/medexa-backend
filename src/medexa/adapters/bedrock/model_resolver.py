"""Resolve Bedrock model IDs with cross-region inference profile fallbacks."""

from __future__ import annotations


def bedrock_model_candidates(model_id: str) -> list[str]:
    """Return model IDs to try in order (primary first)."""
    primary = (model_id or "").strip()
    if not primary:
        return []

    candidates: list[str] = [primary]
    if primary.startswith("us."):
        candidates.append(primary[3:])
    elif primary.startswith("anthropic.") or primary.startswith("amazon.") or primary.startswith("meta."):
        candidates.append(f"us.{primary}")

    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
