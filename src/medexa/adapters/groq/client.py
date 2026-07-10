"""Groq OpenAI-compatible HTTP client (chat + Whisper STT)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"


class GroqClientError(RuntimeError):
    """Raised when Groq API returns an error or unexpected payload."""


class GroqClient:
    """Thin Groq HTTP client — chat completions + audio transcriptions."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Groq API key is required")
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
        }

    def chat(
        self,
        *,
        model: str,
        system: str,
        user_message: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                f"{self._base_url}/chat/completions",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=payload,
            )
        if response.status_code >= 400:
            raise GroqClientError(f"Groq chat failed ({response.status_code}): {response.text[:400]}")
        data = response.json()
        try:
            return str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise GroqClientError(f"Unexpected Groq chat payload: {json.dumps(data)[:400]}") from exc

    def transcribe_audio(
        self,
        *,
        audio: bytes,
        filename: str,
        content_type: str,
        model: str,
        language: str = "en",
        response_format: str = "verbose_json",
    ) -> dict[str, Any]:
        files = {"file": (filename, audio, content_type or "application/octet-stream")}
        data = {
            "model": model,
            "language": language,
            "response_format": response_format,
            "timestamp_granularities[]": "segment",
        }
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                f"{self._base_url}/audio/transcriptions",
                headers=self._headers(),
                data=data,
                files=files,
            )
        if response.status_code >= 400:
            raise GroqClientError(
                f"Groq whisper failed ({response.status_code}): {response.text[:400]}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise GroqClientError(f"Unexpected Groq whisper payload: {json.dumps(payload)[:400]}")
        return payload
