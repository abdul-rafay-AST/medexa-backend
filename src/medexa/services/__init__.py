"""Swappable, AWS-ready service seams.

Every service in this package is defined as a ``typing.Protocol`` (the port) with
one or more concrete adapters:

* A **local, rules-based** implementation that runs with zero external
  dependencies — this is the default and powers the MVP demo.
* An **AWS** implementation (AWS Transcribe for speech-to-text, Amazon Bedrock
  for clinical / SOAP generation) that is selected purely via configuration and
  imported lazily, so the local path never needs ``boto3`` installed.

This is the classic Strategy / Adapter pattern: routers depend on the Protocol,
never on a concrete provider, so we can move from "local rules" to "AWS managed
services" without touching a single endpoint.
"""

from medexa.services.clinical_analyzer import ClinicalAnalyzer, RulesClinicalAnalyzer
from medexa.services.soap_generator import RulesSoapGenerator, SoapGenerator
from medexa.services.summary_generator import (
    PatientSummaryGenerator,
    RulesPatientSummaryGenerator,
)
from medexa.services.transcription import (
    TranscriptionProvider,
    TranscriptionResult,
    TranscriptSegment,
)

__all__ = [
    "ClinicalAnalyzer",
    "RulesClinicalAnalyzer",
    "SoapGenerator",
    "RulesSoapGenerator",
    "PatientSummaryGenerator",
    "RulesPatientSummaryGenerator",
    "TranscriptionProvider",
    "TranscriptionResult",
    "TranscriptSegment",
]
