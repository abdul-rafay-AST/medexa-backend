from __future__ import annotations

from medexa.adapters.bedrock.clinical_assistant import BedrockClinicalAssistant
from medexa.adapters.clinical_assistant.no_op import NoOpClinicalAssistant
from medexa.adapters.groq.clinical_assistant import GroqClinicalAssistant
from medexa.adapters.groq.documentation_generator import GroqDocumentationGenerator
from medexa.adapters.guardrails.local_guardrails import LocalGuardrails
from medexa.config import MedexaConfig
from medexa.services import llm_provider_resolver as resolver
from medexa.services.providers import build_clinical_assistant, build_documentation_service


def test_bedrock_unavailable_falls_back_to_groq(monkeypatch) -> None:
    monkeypatch.setattr(
        resolver,
        "_probe_bedrock",
        lambda model_id, region: (False, "no credentials"),
    )
    resolver.clear_resolver_cache()

    settings = MedexaConfig(
        path_b_enabled=True,
        path_b_provider="bedrock",
        soap_generator="bedrock",
        summary_generator="bedrock",
        groq_api_key="gsk_test_key",
    )
    guardrails = LocalGuardrails()
    resolved = resolver.resolve_llm_providers(settings, force_refresh=True)

    assert resolved.path_b_backend == "groq"
    assert resolved.path_c_backend == "groq"
    assert isinstance(build_clinical_assistant(settings, guardrails, resolved=resolved), GroqClinicalAssistant)
    docs = build_documentation_service(settings, guardrails, resolved=resolved)
    assert isinstance(docs._generator, GroqDocumentationGenerator)  # noqa: SLF001


def test_bedrock_unavailable_without_groq_uses_noop_and_rules(monkeypatch) -> None:
    monkeypatch.setattr(
        resolver,
        "_probe_bedrock",
        lambda model_id, region: (False, "no credentials"),
    )
    resolver.clear_resolver_cache()

    settings = MedexaConfig(
        path_b_enabled=True,
        path_b_provider="bedrock",
        soap_generator="bedrock",
        summary_generator="bedrock",
        groq_api_key=None,
    )
    guardrails = LocalGuardrails()
    resolved = resolver.resolve_llm_providers(settings, force_refresh=True)

    assert resolved.path_b_backend == "noop"
    assert resolved.path_c_backend == "rules"
    assert isinstance(build_clinical_assistant(settings, guardrails, resolved=resolved), NoOpClinicalAssistant)


def test_bedrock_available_uses_bedrock(monkeypatch) -> None:
    monkeypatch.setattr(
        resolver,
        "_probe_bedrock",
        lambda model_id, region: (True, "ok"),
    )
    resolver.clear_resolver_cache()

    settings = MedexaConfig(
        path_b_enabled=True,
        path_b_provider="bedrock",
        soap_generator="bedrock",
        summary_generator="bedrock",
        groq_api_key="gsk_test_key",
    )
    guardrails = LocalGuardrails()
    resolved = resolver.resolve_llm_providers(settings, force_refresh=True)

    assert resolved.path_b_backend == "bedrock"
    assert resolved.path_c_backend == "bedrock"
    assert isinstance(
        build_clinical_assistant(settings, guardrails, resolved=resolved),
        BedrockClinicalAssistant,
    )
