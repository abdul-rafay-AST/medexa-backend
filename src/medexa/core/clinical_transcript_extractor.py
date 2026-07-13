"""Deterministic clinical fact extraction from therapy session transcripts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class InterventionBlock:
    category: str
    duration_minutes: int | None
    details: str
    cpt_code: str | None = None


@dataclass
class TranscriptClinicalFacts:
    pain_scales: list[str] = field(default_factory=list)
    rom_measurements: list[str] = field(default_factory=list)
    manual_therapy_details: list[str] = field(default_factory=list)
    exercise_details: list[str] = field(default_factory=list)
    intervention_blocks: list[InterventionBlock] = field(default_factory=list)
    symptoms: list[str] = field(default_factory=list)
    denies_radicular: bool = False
    diagnoses_mentioned: list[str] = field(default_factory=list)
    hep_mentions: list[str] = field(default_factory=list)
    mmt_documented: bool = False
    session_duration_minutes: int | None = None
    compliance_gaps: list[str] = field(default_factory=list)


_ROM_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:shoulder\s+)?flexion\s+(?:is\s+)?(?:limited\s+to\s+)?(?:about\s+)?(\d+)\s*degrees?", re.I), "Shoulder flexion {value} degrees"),
    (re.compile(r"external\s+rotation\s+(?:is\s+)?(?:also\s+)?(?:restricted\s+to\s+)?(?:around\s+)?(\d+)\s*degrees?", re.I), "External rotation {value} degrees"),
    (re.compile(r"abduction\s+(?:to\s+)?(\d+)\s*degrees?", re.I), "Abduction {value} degrees"),
    (re.compile(r"(\d+)\s*degrees?\s+(?:of\s+)?(?:shoulder\s+)?flexion", re.I), "Shoulder flexion {value} degrees"),
)

_MANUAL_THERAPY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"grade\s+(?:two\s+to\s+three|three|two|four|iii|ii|iv|3|2|4)\s+.*?(?:inferior|anterior).*?(?:glenohumeral|gh)\s+joint\s+mobilizations?",
        re.I,
    ),
    re.compile(r"joint\s+mobilizations?.*?(?:glenohumeral|gh)", re.I),
    re.compile(r"soft\s+tissue\s+(?:mobilization|work).*?(?:pectoralis\s+minor|pec\s+minor|upper\s+trapezius|upper\s+trap)", re.I),
    re.compile(r"manual\s+therapy", re.I),
)

_EXERCISE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"isometric\s+external\s+rotations?", re.I),
    re.compile(r"resistance\s+band", re.I),
    re.compile(r"wall\s+walk\s+exercises?", re.I),
    re.compile(r"therapeutic\s+exercise", re.I),
    re.compile(r"(\d+)\s*sets?\s+of\s+(\d+)", re.I),
)

_SYMPTOM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sharp\s+catch", re.I),
    re.compile(r"dull\s+ache", re.I),
    re.compile(r"stiff(?:ness)?", re.I),
    re.compile(r"guarding", re.I),
)

_DIAGNOSIS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"adhesive\s+capsulitis", re.I),
    re.compile(r"frozen\s+shoulder", re.I),
    re.compile(r"rotator\s+cuff", re.I),
)


def extract_transcript_clinical_facts(transcript: str) -> TranscriptClinicalFacts:
    text = transcript.strip()
    lowered = text.lower()
    facts = TranscriptClinicalFacts()

    for match in re.finditer(r"(\d+)\s*(?:out\s+of|/)\s*10", text, re.I):
        value = f"{match.group(1)}/10"
        if value not in facts.pain_scales:
            facts.pain_scales.append(value)

    _extract_contextual_pain_scales(text, lowered, facts)

    for pattern, label in _ROM_PATTERNS:
        for match in pattern.finditer(text):
            rendered = label.format(value=match.group(1))
            if rendered not in facts.rom_measurements:
                facts.rom_measurements.append(rendered)

    for pattern in _MANUAL_THERAPY_PATTERNS:
        for match in pattern.finditer(text):
            snippet = _clean_snippet(match.group(0))
            if snippet and snippet not in facts.manual_therapy_details:
                facts.manual_therapy_details.append(snippet)

    for pattern in _EXERCISE_PATTERNS:
        for match in pattern.finditer(text):
            snippet = _clean_snippet(match.group(0))
            if snippet and snippet not in facts.exercise_details:
                facts.exercise_details.append(snippet)

    for pattern in _SYMPTOM_PATTERNS:
        for match in pattern.finditer(text):
            snippet = _clean_snippet(match.group(0))
            if snippet and snippet not in facts.symptoms:
                facts.symptoms.append(snippet.title())

    for pattern in _DIAGNOSIS_PATTERNS:
        for match in pattern.finditer(text):
            snippet = _clean_snippet(match.group(0))
            if snippet and snippet not in facts.diagnoses_mentioned:
                facts.diagnoses_mentioned.append(snippet.title())

    facts.denies_radicular = bool(
        re.search(r"\b(no|denies?)\b.*?(tingling|numbness|radicular)", lowered)
        or re.search(r"no\s+tingling", lowered)
    )

    facts.mmt_documented = bool(
        re.search(r"\b(mmt|manual\s+muscle\s+test(?:ing)?|muscle\s+strength\s+grade)\b", lowered)
    )

    hep_patterns = (
        r"home\s+exercise\s+program",
        r"\bhep\b",
        r"pendulum\s+exercises?",
        r"exercises?\s+at\s+home",
        r"doing.*home",
    )
    for pattern in hep_patterns:
        for match in re.finditer(pattern, text, re.I):
            snippet = _clean_snippet(match.group(0))
            if snippet and snippet not in facts.hep_mentions:
                facts.hep_mentions.append(snippet)

    manual_minutes = _extract_block_minutes(text, block_type="manual")
    exercise_minutes = _extract_block_minutes(text, block_type="exercise")
    if manual_minutes:
        details = "; ".join(facts.manual_therapy_details) or "Manual therapy interventions"
        facts.intervention_blocks.append(
            InterventionBlock(
                category="Manual Therapy",
                duration_minutes=manual_minutes,
                details=details,
                cpt_code="97140",
            )
        )
    if exercise_minutes:
        details = "; ".join(facts.exercise_details) or "Therapeutic exercise interventions"
        facts.intervention_blocks.append(
            InterventionBlock(
                category="Therapeutic Exercise",
                duration_minutes=exercise_minutes,
                details=details,
                cpt_code="97110",
            )
        )

    if manual_minutes or exercise_minutes:
        facts.session_duration_minutes = (manual_minutes or 0) + (exercise_minutes or 0)
    else:
        total_match = re.search(r"(\d+)\s*(?:minute|min)\s+session", text, re.I)
        if total_match:
            facts.session_duration_minutes = int(total_match.group(1))

    _assess_compliance_gaps(text, facts)
    return facts


def _assess_compliance_gaps(text: str, facts: TranscriptClinicalFacts) -> None:
    lowered = text.lower()
    exercise_started = any(
        token in lowered
        for token in ("resistance band", "therapeutic exercise", "wall walk", "isometric external")
    )
    if exercise_started and not facts.mmt_documented:
        facts.compliance_gaps.append(
            "Baseline manual muscle testing (MMT) was not documented before therapeutic exercise."
        )
        facts.compliance_gaps.append(
            "Suggested fix: document baseline MMT grades for involved muscles before skilled exercise."
        )

    hep_question_early = bool(
        re.search(
            r"(are you|have you been).{0,40}(home exercise|hep|pendulum|exercises at home)",
            lowered,
        )
    )
    patient_asked_hep = "what should i be doing at home" in lowered or "what should i do at home" in lowered
    if facts.hep_mentions and not hep_question_early and patient_asked_hep:
        facts.compliance_gaps.append(
            "Home exercise program (HEP) compliance was not assessed until the patient asked at end of visit."
        )
        facts.compliance_gaps.append(
            "Suggested fix: ask about HEP compliance at the start of the next visit."
        )


def _extract_block_minutes(text: str, *, block_type: str) -> int | None:
    if block_type == "manual":
        patterns = (
            r"(?:spend|spent|about)\s+(\d+)\s*(?:minutes?|mins?).{0,90}(?:manual therapy|joint mobilization|soft tissue)",
            r"(\d+)\s*(?:minutes?|mins?).{0,40}manual therapy",
        )
        keywords = ("manual therapy", "joint mobilization", "soft tissue")
    else:
        patterns = (
            r"(?:spend|spent|about)\s+(\d+)\s*(?:minutes?|mins?).{0,90}(?:therapeutic exercise|these exercises|resistance band|wall walk|isometric)",
            r"(\d+)\s*(?:minutes?|mins?).{0,40}(?:therapeutic exercise|these exercises)",
        )
        keywords = ("therapeutic exercise", "resistance band", "wall walk", "isometric")

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1))

    for keyword in keywords:
        pattern = re.compile(
            rf"(?:spend|spent|about)\s+(\d+)\s*(?:minutes?|mins?).{{0,80}}{re.escape(keyword)}",
            re.I,
        )
        match = pattern.search(text)
        if match:
            return int(match.group(1))
        reverse = re.compile(
            rf"{re.escape(keyword)}.{{0,80}}(?:spend|spent|about)\s+(\d+)\s*(?:minutes?|mins?)",
            re.I,
        )
        match = reverse.search(text)
        if match:
            return int(match.group(1))
    return None


def _clean_snippet(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().rstrip(".,;"))


def _extract_contextual_pain_scales(
    text: str,
    lowered: str,
    facts: TranscriptClinicalFacts,
) -> None:
    """Capture resting vs provocative pain ratings when phrasing distinguishes them."""
    contextual_patterns: tuple[tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"(?:resting|at rest|baseline).{0,40}?(\d+)\s*(?:out\s+of|/)\s*10", re.I), "Resting {value}/10"),
        (re.compile(r"(?:sharp|catch|pinch|movement|overhead).{0,50}?(\d+)\s*(?:out\s+of|/)\s*10", re.I), "Sharp catch {value}/10"),
        (re.compile(r"(\d+)\s*(?:out\s+of|/)\s*10.{0,40}?(?:sharp|catch|pinch)", re.I), "Sharp catch {value}/10"),
        (re.compile(r"(\d+)\s*(?:out\s+of|/)\s*10.{0,40}?(?:resting|at rest)", re.I), "Resting {value}/10"),
    )
    for pattern, label in contextual_patterns:
        for match in pattern.finditer(text):
            rendered = label.format(value=match.group(1))
            if rendered not in facts.pain_scales:
                facts.pain_scales.append(rendered)

    if "adhesive capsulitis" in lowered and not any("capsulitis" in p.lower() for p in facts.pain_scales):
        pass  # diagnosis handled separately
