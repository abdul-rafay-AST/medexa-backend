"""Service provider factory — wires concrete adapters based on configuration.

This is the composition root for the Strategy pattern: the config setting
``MEDEXA_CLINICAL_ANALYZER=bedrock`` (or ``rules``) selects the concrete
adapter, keeping all router code adapter-agnostic.
"""

from __future__ import annotations

from medexa.config import MedexaConfig
from medexa.core.entity_extractor import EntityExtractor
from medexa.loaders.body_region_normalizer import BodyRegionNormalizer
from medexa.loaders.cpt_metadata_loader import CptMetadataLoader
from medexa.loaders.icd_lookup_loader import IcdLookupLoader
from medexa.loaders.ncci_rules_loader import NcciRulesLoader
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


def build_clinical_analyzer(
    settings: MedexaConfig,
    *,
    entity_extractor: EntityExtractor,
    cpt_metadata_loader: CptMetadataLoader,
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
    rules = RulesSoapGenerator()
    if settings.soap_generator == "bedrock":
        return BedrockSoapGenerator(
            fallback=rules, model_id=settings.bedrock_model_id, region_name=settings.aws_region
        )
    return rules


def build_summary_generator(settings: MedexaConfig) -> PatientSummaryGenerator:
    rules = RulesPatientSummaryGenerator()
    if settings.summary_generator == "bedrock":
        return BedrockSummaryGenerator(
            fallback=rules, model_id=settings.bedrock_model_id, region_name=settings.aws_region
        )
    return rules


def build_transcription_provider(settings: MedexaConfig) -> TranscriptionProvider:
    if settings.transcription_provider == "aws_transcribe":
        return AwsTranscribeProvider(
            region_name=settings.aws_region, s3_bucket=settings.transcribe_s3_bucket
        )
    return UnavailableTranscriptionProvider()
