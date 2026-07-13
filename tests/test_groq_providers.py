from __future__ import annotations

from medexa.adapters.bedrock.documentation_generator import RulesDocumentationGenerator
from medexa.adapters.clinical_assistant.no_op import NoOpClinicalAssistant
from medexa.adapters.groq.client import GroqClient
from medexa.adapters.groq.clinical_assistant import GroqClinicalAssistant
from medexa.adapters.groq.documentation_generator import GroqDocumentationGenerator
from medexa.adapters.groq.whisper import GroqWhisperTranscriptionProvider
from medexa.adapters.guardrails.local_guardrails import LocalGuardrails
from medexa.config import MedexaConfig
from medexa.services import llm_provider_resolver as resolver
from medexa.services.providers import (
    build_clinical_assistant,
    build_documentation_service,
    build_transcription_provider,
)
from medexa.services.transcription import UnavailableTranscriptionProvider


def test_providers_select_groq_when_configured() -> None:
    resolver.clear_resolver_cache()
    settings = MedexaConfig(
        path_b_enabled=True,
        path_b_provider="groq",
        soap_generator="groq",
        summary_generator="groq",
        transcription_provider="groq_whisper",
        groq_api_key="gsk_test_key",
    )
    guardrails = LocalGuardrails()
    assistant = build_clinical_assistant(settings, guardrails)
    assert isinstance(assistant, GroqClinicalAssistant)

    docs = build_documentation_service(settings, guardrails)
    assert isinstance(docs._generator, GroqDocumentationGenerator)  # noqa: SLF001

    stt = build_transcription_provider(settings)
    assert isinstance(stt, GroqWhisperTranscriptionProvider)


def test_providers_fallback_without_groq_key() -> None:
    resolver.clear_resolver_cache()
    settings = MedexaConfig(
        path_b_enabled=True,
        path_b_provider="groq",
        soap_generator="groq",
        summary_generator="groq",
        transcription_provider="groq_whisper",
        groq_api_key=None,
    )
    guardrails = LocalGuardrails()
    assert isinstance(build_clinical_assistant(settings, guardrails), NoOpClinicalAssistant)
    docs = build_documentation_service(settings, guardrails)
    assert isinstance(docs._generator, RulesDocumentationGenerator)  # noqa: SLF001
    assert isinstance(build_transcription_provider(settings), UnavailableTranscriptionProvider)


def test_groq_client_rejects_empty_key() -> None:
    try:
        GroqClient(api_key="  ")
        assert False, "expected ValueError"
    except ValueError:
        pass
