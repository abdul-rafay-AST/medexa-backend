"""Service provider factory — wires concrete adapters based on configuration.

Composition root for the Strategy pattern: config selects rules / Bedrock / Groq
adapters while routers stay provider-agnostic.
"""

from __future__ import annotations

import logging

from medexa.adapters.bedrock.clinical_assistant import BedrockClinicalAssistant
from medexa.adapters.bedrock.documentation_generator import (
    BedrockDocumentationGenerator,
    RulesDocumentationGenerator,
)
from medexa.adapters.clinical_assistant.no_op import NoOpClinicalAssistant
from medexa.adapters.groq.clinical_assistant import GroqClinicalAssistant
from medexa.adapters.groq.documentation_generator import GroqDocumentationGenerator
from medexa.adapters.groq.whisper import GroqWhisperTranscriptionProvider
from medexa.adapters.deepgram.nova_transcription import DeepgramNovaTranscriptionProvider
from medexa.application.documentation_service import DocumentationService
from medexa.config import MedexaConfig
from medexa.core.entity_extractor import EntityExtractor
from medexa.loaders.body_region_normalizer import BodyRegionNormalizer
from medexa.loaders.icd_lookup_loader import IcdLookupLoader
from medexa.loaders.ncci_rules_loader import NcciRulesLoader
from medexa.ports.clinical_assistant import ClinicalAssistantPort
from medexa.ports.cpt_metadata import CptMetadataPort
from medexa.ports.documentation_port import DocumentationPort
from medexa.ports.guardrails import GuardrailsPort
from medexa.services.clinical_analyzer import (
    BedrockClinicalAnalyzer,
    ClinicalAnalyzer,
    RulesClinicalAnalyzer,
)
from medexa.services.soap_generator import (
    BedrockSoapGenerator,
    RulesSoapGenerator,
    SoapGenerator,
)
from medexa.services.summary_generator import (
    BedrockSummaryGenerator,
    PatientSummaryGenerator,
    RulesPatientSummaryGenerator,
)
from medexa.services.transcription import (
    AwsTranscribeProvider,
    TranscriptionProvider,
    UnavailableTranscriptionProvider,
)

from medexa.services.llm_provider_resolver import ResolvedLlmProviders, resolve_llm_providers

logger = logging.getLogger(__name__)


def _groq_key(settings: MedexaConfig) -> str | None:
    key = (settings.groq_api_key or "").strip()
    return key or None


def _deepgram_key(settings: MedexaConfig) -> str | None:
    key = (settings.deepgram_api_key or "").strip()
    return key or None


def build_documentation_service(
    settings: MedexaConfig,
    guardrails: GuardrailsPort,
    *,
    icd_loader: IcdLookupLoader | None = None,
    resolved: ResolvedLlmProviders | None = None,
) -> DocumentationService:
    rules = RulesDocumentationGenerator()
    active = resolved or resolve_llm_providers(settings)

    generator: DocumentationPort
    if active.path_c_backend == "groq":
        api_key = _groq_key(settings)
        if not api_key:
            logger.warning("groq_path_c_missing_key_fallback_rules")
            generator = rules
        else:
            generator = GroqDocumentationGenerator(
                fallback=rules,
                api_key=api_key,
                model_id=settings.groq_path_c_model_id or settings.path_c_model_id,
                guardrails=guardrails,
                base_url=settings.groq_base_url,
            )
    elif active.path_c_backend == "bedrock":
        groq_fallback = _build_groq_documentation(settings, guardrails, rules)
        generator = BedrockDocumentationGenerator(
            fallback=groq_fallback or rules,
            model_id=settings.path_c_model_id,
            region_name=settings.aws_region,
            guardrails=guardrails,
        )
    else:
        generator = rules
    return DocumentationService(generator, icd_loader=icd_loader)


def _build_groq_documentation(
    settings: MedexaConfig,
    guardrails: GuardrailsPort,
    rules: RulesDocumentationGenerator,
) -> GroqDocumentationGenerator | None:
    api_key = _groq_key(settings)
    if not api_key:
        return None
    return GroqDocumentationGenerator(
        fallback=rules,
        api_key=api_key,
        model_id=settings.groq_path_c_model_id or settings.path_c_model_id,
        guardrails=guardrails,
        base_url=settings.groq_base_url,
    )


def build_clinical_assistant(
    settings: MedexaConfig,
    guardrails: GuardrailsPort,
    resolved: ResolvedLlmProviders | None = None,
) -> ClinicalAssistantPort:
    active = resolved or resolve_llm_providers(settings)
    if active.path_b_backend == "noop":
        return NoOpClinicalAssistant()

    if active.path_b_backend == "groq":
        api_key = _groq_key(settings)
        if not api_key:
            logger.warning("groq_path_b_missing_key_fallback_noop")
            return NoOpClinicalAssistant()
        return GroqClinicalAssistant(
            api_key=api_key,
            model_id=settings.groq_path_b_model_id or settings.path_b_model_id,
            guardrails=guardrails,
            base_url=settings.groq_base_url,
        )

    groq_assistant = _build_groq_assistant(settings, guardrails)
    return BedrockClinicalAssistant(
        model_id=settings.path_b_model_id,
        region_name=settings.aws_region,
        guardrails=guardrails,
        groq_fallback=groq_assistant,
    )


def _build_groq_assistant(
    settings: MedexaConfig,
    guardrails: GuardrailsPort,
) -> GroqClinicalAssistant | None:
    api_key = _groq_key(settings)
    if not api_key:
        return None
    return GroqClinicalAssistant(
        api_key=api_key,
        model_id=settings.groq_path_b_model_id or settings.path_b_model_id,
        guardrails=guardrails,
        base_url=settings.groq_base_url,
    )


def build_clinical_analyzer(
    settings: MedexaConfig,
    *,
    entity_extractor: EntityExtractor,
    cpt_metadata_loader: CptMetadataPort,
    icd_loader: IcdLookupLoader,
    ncci_loader: NcciRulesLoader,
    region_normalizer: BodyRegionNormalizer,
) -> ClinicalAnalyzer:
    rules = RulesClinicalAnalyzer(
        entity_extractor=entity_extractor,
        cpt_metadata_loader=cpt_metadata_loader,
        icd_loader=icd_loader,
        ncci_loader=ncci_loader,
        region_normalizer=region_normalizer,
    )
    if settings.clinical_analyzer == "bedrock":
        return BedrockClinicalAnalyzer(
            fallback=rules, model_id=settings.bedrock_model_id, region_name=settings.aws_region
        )
    return rules


def build_soap_generator(settings: MedexaConfig) -> SoapGenerator:
    """Legacy SOAP endpoint helper — Path C finalize uses DocumentationService."""
    rules = RulesSoapGenerator()
    if settings.soap_generator == "bedrock":
        return BedrockSoapGenerator(
            fallback=rules,
            model_id=settings.path_c_model_id,
            region_name=settings.aws_region,
        )
    return rules


def build_summary_generator(settings: MedexaConfig) -> PatientSummaryGenerator:
    rules = RulesPatientSummaryGenerator()
    if settings.summary_generator == "bedrock":
        return BedrockSummaryGenerator(
            fallback=rules,
            model_id=settings.path_c_model_id,
            region_name=settings.aws_region,
        )
    return rules


def build_transcription_provider(settings: MedexaConfig) -> TranscriptionProvider:
    if settings.transcription_provider == "deepgram":
        api_key = _deepgram_key(settings)
        if not api_key:
            logger.warning("deepgram_missing_key_fallback_unavailable")
            return UnavailableTranscriptionProvider()
        return DeepgramNovaTranscriptionProvider(
            api_key=api_key,
            model=settings.deepgram_model.strip(),
            diarize_model=(settings.deepgram_diarize_model or "").strip() or None,
            base_url=settings.deepgram_base_url,
            language=settings.deepgram_language,
        )
    if settings.transcription_provider == "groq_whisper":
        api_key = _groq_key(settings)
        if not api_key:
            logger.warning("groq_whisper_missing_key_fallback_unavailable")
            return UnavailableTranscriptionProvider()
        return GroqWhisperTranscriptionProvider(
            api_key=api_key,
            model_id=settings.groq_whisper_model_id,
            base_url=settings.groq_base_url,
        )
    if settings.transcription_provider == "aws_transcribe":
        bucket = settings.transcribe_s3_bucket or settings.s3_bucket
        return AwsTranscribeProvider(
            region_name=settings.aws_region, s3_bucket=bucket
        )
    return UnavailableTranscriptionProvider()
