"""Clinical analysis service — Strategy pattern with Rules and Bedrock adapters.

The ``ClinicalAnalyzer`` protocol defines the port. Two adapters are provided:

* ``RulesClinicalAnalyzer`` — deterministic, flat-file, zero-dependency analysis
  using keyword heuristics and CPT/ICD/NCCI lookup tables.
* ``BedrockClinicalAnalyzer`` — invokes Amazon Bedrock (Claude) for richer,
  context-aware clinical interpretation with the rules engine as fallback.

Healthcare compliance:
  * Every output carries a mandatory disclaimer requiring clinician review.
  * No PHI is logged or persisted beyond the session state repository.
  * ICD-10 and CPT suggestions are AI-generated *drafts*, never auto-applied.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol, runtime_checkable

from medexa.core.entity_extractor import EntityExtractor
from medexa.loaders.body_region_normalizer import BodyRegionNormalizer
from medexa.loaders.cpt_metadata_loader import CptMetadataLoader
from medexa.loaders.icd_lookup_loader import IcdLookupLoader
from medexa.loaders.ncci_rules_loader import NcciRulesLoader
from medexa.schemas import (
    BodyRegionMention,
    ClinicalAnalysis,
    Confidence,
    CptSuggestionDetail,
    IcdSuggestion,
    NcciConflictDetail,
    SoapUpdate,
)

logger = logging.getLogger(__name__)

_DISCLAIMER = "AI-generated suggestions require clinician review before use."

# Symptom / impression keyword rules. Ported from the frontend heuristic
# analyzer so local behaviour matches the UI's fallback exactly, then enriched
# with the flat-file ICD/CPT lookups below.
#   (trigger phrases, diagnosis label | None, symptom label | None, billing hint | None)
_KEYWORD_RULES: list[tuple[tuple[str, ...], str | None, str | None, str | None]] = [
    (("back pain", "lower back", "lumbar"), "Low back pain / musculoskeletal pain", "Back pain",
     "Therapeutic activity or therapeutic exercise may be relevant if skilled intervention is documented."),
    (("knee pain", "knee stiffness"), "Knee pain / possible mobility limitation", "Knee pain",
     "Gait training, therapeutic exercise, or neuromuscular re-education may be relevant based on treatment performed."),
    (("shoulder pain", "shoulder stiffness"), "Shoulder pain / possible range of motion limitation", "Shoulder pain", None),
    (("anxiety", "panic", "worried"), "Anxiety-related symptoms", "Anxiety", None),
    (("depression", "depressed", "low mood"), "Depressive symptoms", "Low mood", None),
    (("headache",), "Headache symptoms", "Headache", None),
    (("fever",), None, "Fever", None),
    (("cough",), None, "Cough", None),
    (("dizziness",), "Dizziness symptoms", "Dizziness", None),
    (("numbness",), "Possible neurological sensory symptoms", "Numbness", None),
    (("weakness",), "Weakness / reduced strength symptoms", "Weakness", None),
    (("sleep", "trouble sleeping", "poor sleep", "insomnia"), "Sleep disturbance", "Sleep disturbance", None),
    (("trauma", "fall", "injury"), "Possible injury or trauma-related symptoms", "Trauma or injury history", None),
    (("difficulty walking",), "Possible mobility limitation", "Difficulty walking", None),
]


@runtime_checkable
class ClinicalAnalyzer(Protocol):
    """Port: interpret a transcript segment into a structured clinical analysis.

    The default adapter is :class:`RulesClinicalAnalyzer`. An Amazon Bedrock
    adapter can be dropped in later behind this same interface (see
    :class:`BedrockClinicalAnalyzer`)."""

    def analyze(self, transcript: str) -> ClinicalAnalysis: ...


class RulesClinicalAnalyzer:
    """Deterministic, flat-file clinical analyzer (no LLM, no network).

    Combines four in-memory lookups:
      * activity synonyms + CPT lookup  -> ``cpt_suggestions``
      * ICD-10 phrase table             -> ``icd10_suggestions`` / diagnoses
      * body-region normalizer          -> ``body_regions``
      * NCCI PTP edits                  -> ``ncci_conflicts``
    plus keyword heuristics for symptoms, billing hints, and a drafted SOAP
    update. Output is suitable for direct clinician review and mirrors the
    schema an LLM adapter would later produce.
    """

    def __init__(
        self,
        entity_extractor: EntityExtractor,
        cpt_metadata_loader: CptMetadataLoader,
        icd_loader: IcdLookupLoader,
        ncci_loader: NcciRulesLoader,
        region_normalizer: BodyRegionNormalizer,
    ) -> None:
        self._extractor = entity_extractor
        self._meta = cpt_metadata_loader
        self._icd = icd_loader
        self._ncci = ncci_loader
        self._regions = region_normalizer

    def analyze(self, transcript: str) -> ClinicalAnalysis:
        text = (transcript or "").strip()
        normalized = text.lower()

        symptoms: list[str] = []
        diagnoses: list[str] = []
        billing_hints: list[str] = []

        for triggers, diagnosis, symptom, hint in _KEYWORD_RULES:
            if any(t in normalized for t in triggers):
                if diagnosis:
                    diagnoses.append(diagnosis)
                if symptom:
                    symptoms.append(symptom)
                if hint:
                    billing_hints.append(hint)

        if "cough" in normalized and "fever" in normalized:
            diagnoses.append("Possible respiratory infection symptoms")

        icd_suggestions = self._icd_suggestions(normalized)
        for icd in icd_suggestions:
            diagnoses.append(f"{icd.phrase.title()} ({icd.code})")

        body_regions = self._body_regions(normalized)
        cpt_suggestions = self._cpt_suggestions(text)
        for cpt in cpt_suggestions:
            billing_hints.append(
                f"Documented '{', '.join(cpt.matched_phrases)}' may support {cpt.display_name} ({cpt.code})."
            )
        ncci_conflicts = self._ncci_conflicts([c.code for c in cpt_suggestions])

        symptoms = _unique(symptoms)
        diagnoses = _unique(diagnoses)
        billing_hints = _unique(billing_hints)
        confidence = self._confidence(text, diagnoses, symptoms, cpt_suggestions)

        return ClinicalAnalysis(
            summary=self._summary(text),
            possible_clinical_impressions=diagnoses[:5],
            possible_diagnoses=diagnoses or ["No specific possible diagnosis detected from this segment"],
            icd10_suggestions=icd_suggestions,
            body_regions=body_regions,
            cpt_suggestions=cpt_suggestions,
            ncci_conflicts=ncci_conflicts,
            symptoms=symptoms or ["No clear symptom keywords detected"],
            soap_update=self._soap_update(normalized, symptoms, diagnoses, billing_hints, body_regions),
            billing_hints=billing_hints or ["No specific CPT or billing relevance detected in this segment"],
            confidence=confidence,
            disclaimer=_DISCLAIMER,
        )

    # -- enrichment helpers --------------------------------------------------
    def _icd_suggestions(self, normalized: str) -> list[IcdSuggestion]:
        suggestions: list[IcdSuggestion] = []
        for phrase, code in self._icd.find_matches(normalized):
            # Longer, more specific phrases earn higher confidence.
            confidence: Confidence = "high" if len(phrase.split()) >= 3 else "medium"
            suggestions.append(
                IcdSuggestion(
                    phrase=phrase,
                    code=code,
                    reason=f"Transcript phrase '{phrase}' maps to ICD-10 {code}.",
                    confidence=confidence,
                )
            )
        return suggestions

    def _body_regions(self, normalized: str) -> list[BodyRegionMention]:
        return [
            BodyRegionMention(phrase=phrase, region=region)
            for phrase, region in self._regions.find_all_regions(normalized)
        ]

    def _cpt_suggestions(self, text: str) -> list[CptSuggestionDetail]:
        # Reuse the same entity extractor that drives live billing so the
        # documentation layer never disagrees with the timer/units layer.
        entities = self._extractor.extract(text, chunk_id="analysis")
        by_code: dict[str, CptSuggestionDetail] = {}
        for entity in entities:
            code = entity.possible_cpt
            if not code:
                continue
            meta = self._meta.get(code)
            if code in by_code:
                if entity.matched_phrase not in by_code[code].matched_phrases:
                    by_code[code].matched_phrases.append(entity.matched_phrase)
                continue
            by_code[code] = CptSuggestionDetail(
                code=code,
                label=(meta or {}).get("label", code),
                display_name=self._meta.get_display_name(code),
                descriptor=(meta or {}).get("descriptor", ""),
                matched_phrases=[entity.matched_phrase],
                documentation_requirements=list((meta or {}).get("documentation_requirements", [])),
                billing_caveats=dict((meta or {}).get("billing_caveats", {})),
                reason=(meta or {}).get("clinical_rationale", "Detected billable activity in transcript."),
                confidence=(meta or {}).get("confidence", "high"),
            )
        return list(by_code.values())

    def _ncci_conflicts(self, codes: list[str]) -> list[NcciConflictDetail]:
        conflicts: list[NcciConflictDetail] = []
        seen: set[tuple[str, str]] = set()
        unique_codes = sorted(set(codes))
        for i in range(len(unique_codes)):
            for j in range(i + 1, len(unique_codes)):
                rule = self._ncci.check_conflict(unique_codes[i], unique_codes[j])
                if not rule:
                    continue
                key = tuple(sorted((rule["cpt_a"], rule["cpt_b"])))
                if key in seen:
                    continue
                seen.add(key)  # type: ignore[arg-type]
                conflicts.append(
                    NcciConflictDetail(
                        cpt_a=rule["cpt_a"],
                        cpt_b=rule["cpt_b"],
                        conflict_type=rule["conflict_type"],
                        body_region_sensitive=rule["body_region_sensitive"],
                        modifier_59_possible=rule["modifier_59_possible"],
                        explanation=rule["explanation"],
                        severity="warning" if rule["modifier_59_possible"] else "info",
                    )
                )
        return conflicts

    @staticmethod
    def _summary(text: str) -> str:
        clean = " ".join(text.split())
        if not clean:
            return "No clinically meaningful speech was captured in this segment."
        snippet = clean[:220] + ("..." if len(clean) > 220 else "")
        return f"Conversation segment reviewed: {snippet}"

    @staticmethod
    def _confidence(
        text: str,
        diagnoses: list[str],
        symptoms: list[str],
        cpts: list[CptSuggestionDetail],
    ) -> Confidence:
        clean = " ".join(text.split())
        if len(clean) < 20:
            return "low"
        signal = len(diagnoses) + len(symptoms) + len(cpts)
        return "high" if signal >= 4 else "medium"

    @staticmethod
    def _soap_update(
        normalized: str,
        symptoms: list[str],
        diagnoses: list[str],
        hints: list[str],
        regions: list[BodyRegionMention],
    ) -> SoapUpdate:
        subjective = (
            f"Patient discussed {', '.join(s.lower() for s in symptoms)} during this segment."
            if symptoms
            else "No additional subjective symptom details detected in this segment."
        )
        objective = (
            "Consider documenting observed mobility, strength, and range of motion findings."
            if any(k in normalized for k in ("mobility", "range of motion", "weakness"))
            else "No new objective findings detected from speech alone."
        )
        assessment = (
            f"Possible clinical impressions to review: {'; '.join(diagnoses)}."
            if diagnoses
            else "No new assessment impression suggested by this segment."
        )
        plan = (
            "Review therapy plan, skilled minutes, and documentation support for the detected treatment themes."
            if hints
            else "Continue clinician review before adding generated suggestions to the note."
        )
        return SoapUpdate(subjective=subjective, objective=objective, assessment=assessment, plan=plan)


class BedrockClinicalAnalyzer:
    """Amazon Bedrock adapter — invokes a foundation model for clinical analysis.

    When AWS credentials and a Bedrock model ID are configured, this adapter
    sends the transcript plus structured CPT/ICD/NCCI context to a Bedrock
    foundation model (e.g. Claude) and parses the JSON response into
    :class:`ClinicalAnalysis`.

    Falls back to the deterministic rules analyzer on any error so the API
    endpoint keeps working regardless of AWS availability.
    """

    def __init__(
        self,
        fallback: ClinicalAnalyzer,
        model_id: str,
        region_name: str | None = None,
    ) -> None:
        self._fallback = fallback
        self._model_id = model_id
        self._region_name = region_name or "us-east-1"
        self._client = None

    def _get_client(self):
        """Lazy-init boto3 client — avoids import unless Bedrock is actually used."""
        if self._client is None:
            import boto3  # noqa: PLC0415

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self._region_name,
            )
        return self._client

    def analyze(self, transcript: str) -> ClinicalAnalysis:
        """Invoke Bedrock for clinical analysis with rules-engine fallback."""
        if not transcript or not transcript.strip():
            return self._fallback.analyze(transcript)

        try:
            client = self._get_client()
            prompt = self._build_prompt(transcript)

            response = client.invoke_model(
                modelId=self._model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4096,
                    "temperature": 0.1,
                    "messages": [{"role": "user", "content": prompt}],
                }),
            )

            response_body = json.loads(response["body"].read())
            content = response_body.get("content", [{}])[0].get("text", "")

            return self._parse_response(content, transcript)

        except Exception:
            logger.warning(
                "bedrock_clinical_fallback",
                exc_info=True,
                extra={"extra_fields": {"model_id": self._model_id}},
            )
            return self._fallback.analyze(transcript)

    def _build_prompt(self, transcript: str) -> str:
        """Build a structured clinical analysis prompt for the foundation model."""
        return f"""You are a clinical documentation assistant for physical therapy.
Analyze the following therapy session transcript and return a JSON object with:

1. "summary": Brief clinical summary of the conversation
2. "possible_diagnoses": List of possible diagnoses mentioned
3. "symptoms": List of symptoms mentioned
4. "icd10_suggestions": List of objects with "phrase", "code", "reason", "confidence"
5. "body_regions": List of objects with "phrase", "region"
6. "cpt_suggestions": List of objects with "code", "label", "display_name", "descriptor", "matched_phrases", "reason", "confidence"
7. "soap_update": Object with "subjective", "objective", "assessment", "plan"
8. "billing_hints": List of billing-relevant observations
9. "confidence": Overall confidence ("low", "medium", "high")

IMPORTANT: This is an AI-assist tool. All suggestions require licensed clinician review.
Do NOT diagnose — suggest possible clinical impressions for clinician confirmation.

Transcript:
{transcript}

Return ONLY valid JSON, no markdown formatting."""

    def _parse_response(self, content: str, transcript: str) -> ClinicalAnalysis:
        """Parse Bedrock model response into ClinicalAnalysis, falling back on error."""
        try:
            # Strip markdown code fences if present.
            clean = content.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()

            data = json.loads(clean)

            cpt_suggestions = [
                CptSuggestionDetail(
                    code=cpt.get("code", ""),
                    label=cpt.get("label", ""),
                    display_name=cpt.get("display_name", cpt.get("label", "")),
                    descriptor=cpt.get("descriptor", ""),
                    matched_phrases=cpt.get("matched_phrases", []),
                    documentation_requirements=cpt.get("documentation_requirements", []),
                    billing_caveats=cpt.get("billing_caveats", {}),
                    reason=cpt.get("reason", ""),
                    confidence=cpt.get("confidence", "medium"),
                )
                for cpt in data.get("cpt_suggestions", [])
            ]

            # NCCI is always rules-derived (CMS PTP edits), even when CPT/ICD
            # impressions come from Bedrock — golden rule #1 for billing safety.
            ncci_conflicts: list[NcciConflictDetail] = []
            if isinstance(self._fallback, RulesClinicalAnalyzer):
                codes = [c.code for c in cpt_suggestions if c.code]
                ncci_conflicts = self._fallback._ncci_conflicts(codes)

            return ClinicalAnalysis(
                summary=data.get("summary", ""),
                possible_clinical_impressions=data.get("possible_diagnoses", [])[:5],
                possible_diagnoses=data.get("possible_diagnoses", []),
                icd10_suggestions=[
                    IcdSuggestion(**icd) for icd in data.get("icd10_suggestions", [])
                ],
                body_regions=[
                    BodyRegionMention(**br) for br in data.get("body_regions", [])
                ],
                cpt_suggestions=cpt_suggestions,
                ncci_conflicts=ncci_conflicts,
                symptoms=data.get("symptoms", []),
                soap_update=SoapUpdate(**data.get("soap_update", {})),
                billing_hints=data.get("billing_hints", []),
                confidence=data.get("confidence", "medium"),
                disclaimer=_DISCLAIMER,
            )
        except (json.JSONDecodeError, TypeError, KeyError):
            logger.warning("bedrock_response_parse_failed", exc_info=True)
            return self._fallback.analyze(transcript)


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
