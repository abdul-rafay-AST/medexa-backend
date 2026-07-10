"""Deepgram pre-recorded listen API client."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepgram.com"
DEFAULT_TIMEOUT_SECONDS = 90.0


class DeepgramClientError(RuntimeError):
    """Raised when Deepgram returns an error or an unexpected payload."""


class DeepgramClient:
    """Thin HTTP client for Deepgram /v1/listen (batch transcription)."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Deepgram API key is required")
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def transcribe_file(
        self,
        *,
        audio: bytes,
        content_type: str,
        model: str,
        diarize_model: str = "latest",
        language: str = "en-US",
    ) -> dict[str, Any]:
        """Transcribe raw audio bytes with medical model + speaker diarization."""
        params = {
            "model": model,
            "diarize_model": diarize_model,
            "smart_format": "true",
            "punctuate": "true",
            "utterances": "true",
            "language": language,
        }
        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": content_type,
        }
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                f"{self._base_url}/v1/listen",
                headers=headers,
                params=params,
                content=audio,
            )
        if response.status_code >= 400:
            raise DeepgramClientError(
                f"Deepgram listen failed ({response.status_code}): {response.text[:400]}"
            )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise DeepgramClientError(
                f"Deepgram returned non-JSON body: {response.text[:200]}"
            ) from exc
        if not isinstance(payload, dict):
            raise DeepgramClientError("Deepgram response must be a JSON object")
        return payload
