# Medexa Arabic Path A and Path B Implementation Plan

## Document status

- **Status:** Proposed implementation baseline
- **Date:** 21 July 2026
- **Primary market:** Saudi Arabia (KSA)
- **Existing markets preserved:** United States
- **Future market:** United Arab Emirates
- **Architecture authority:** This document extends [ADR-001](docs/adr/001-three-path-pipeline.md) and [ADR-002](docs/adr/002-multi-region-billing.md). If an implementation choice conflicts with an accepted ADR, create a superseding ADR before changing production behavior.

> This is an engineering and compliance-readiness plan, not legal advice or a certification of compliance. Saudi, US, and UAE privacy, health-data, coding, contractual, and data-residency decisions require approval from qualified legal, privacy, security, and clinical-coding owners before production launch.

## 1. Objective

Implement a low-latency Arabic clinical intelligence pipeline that:

1. receives native Arabic streaming transcripts from Amazon Transcribe;
2. preserves the original Arabic evidence without runtime translation;
3. uses open-weight multilingual NLP to identify clinically meaningful spans;
4. retrieves SBS and ICD-10-AM candidates using BGE-M3 and FAISS;
5. keeps Path A deterministic, explainable, auditable, and free of LLM decisions;
6. uses extracted clinical events to wake Path B only when useful;
7. produces Arabic and English UI output from language-neutral structured results;
8. preserves the existing US CPT/NCCI/8-minute-rule behavior; and
9. adds UAE support later through the existing `RegionRegistry`/`RegionBundle` extension points.

## 2. Non-negotiable system invariants

These invariants are architectural constraints, not optional recommendations:

- **Path A is the billing source of truth.** An LLM must never select, approve, submit, or override a billing code.
- **Retrieval is not validation.** BGE-M3/FAISS may return candidates; deterministic regional rules decide whether a candidate is displayable.
- **Abstention is a valid result.** When evidence is weak, conflicting, negated, planned rather than performed, or ambiguous, Path A returns no code or an ambiguity alert.
- **Path B has no billing authority.** It may suggest documentation improvements or clinical questions only.
- **The original transcript is immutable evidence.** Normalization creates a derived field and never overwrites native Arabic text.
- **Nothing is submitted automatically.** A licensed clinician reviews outputs before documentation or claim submission.
- **One backend, regional bundles.** KSA and UAE do not fork the core pipeline.
- **No PHI in vector catalogues.** SBS/ICD/CPT indexes contain terminology and rules only, never patient or session data.
- **No PHI in logs, metrics, traces, exception responses, or model-training datasets by default.**
- **All external processors are deny-by-default.** A provider is enabled only after contractual, regional, privacy, security, and service-eligibility review.

## 3. Target architecture

```text
Client audio
  -> Amazon Transcribe Streaming (ar-SA)
  -> immutable Arabic transcript chunk
  -> conservative Arabic normalizer
  -> shared clinical span extractor (multilingual GLiNER adapter)
       |-> Path A: assertion/negation -> catalogue router -> BGE-M3 -> FAISS
       |           -> SQLite metadata -> deterministic regional validators
       |           -> structured code suggestion / ambiguity / abstention
       |
       `-> Path B: domain events -> deterministic trigger evaluator
                   -> dedupe + debounce + rate limits
                   -> minimum-necessary context builder
                   -> Bedrock guardrails + clinical assistant
                   -> Arabic localized suggestion

All outputs -> audit events -> clinician review -> optional Path C after session
```

### Component responsibilities

| Component | Responsibility | Explicitly prohibited |
|---|---|---|
| Amazon Transcribe | Produce native Arabic transcript segments | Coding or clinical decisions |
| Arabic normalizer | Produce searchable normalized Arabic while retaining source offsets | Destructive rewriting of evidence |
| GLiNER adapter | Detect candidate spans/events such as symptom, procedure, body site, severity, duration and authorization reference | Final SBS/ICD selection |
| BGE-M3 adapter | Create multilingual embeddings | Billing validation |
| FAISS | Return nearest vector IDs and distances | Store clinical metadata or rules |
| SQLite catalogue | Map vector IDs to versioned terminology and deterministic attributes | Store session PHI |
| Regional validators | Apply active dates, region, assertion, authorization, evidence and exclusion rules | Use LLM output as authority |
| Path B trigger evaluator | Convert meaningful domain events into sparse LLM calls | Trigger on every transcript chunk |
| Bedrock assistant | Generate concise documentation/clinical assistance in the selected language | Assert billable codes or submit claims |

## 4. Technology decisions

### 4.1 Initial models

- **Entity extraction:** `urchade/gliner_multi-v2.1`, pinned to an immutable model revision and verified Apache-2.0 artefacts.
- **Multilingual retrieval:** `BAAI/bge-m3`, pinned to an immutable revision and verified MIT artefacts.
- **Runtime:** ONNX Runtime on CPU where a verified export meets accuracy parity; otherwise PyTorch behind the same port.
- **Vector index:** FAISS `IndexFlatIP` for the first release. With roughly 10,000 SBS records, exact cosine retrieval is small, predictable, and avoids approximate-index tuning errors.
- **Metadata:** read-only SQLite. SQLite is an embedded file, not a server and not Amazon RDS.

The initial release requires no model fine-tuning. It does require clinical evaluation and threshold calibration. “Pretrained” does not mean “validated for Saudi therapy speech.”

### 4.2 Why FAISS plus SQLite

FAISS returns vector IDs and similarity values. It does not contain effective dates, code-system versions, descriptions, Arabic aliases, exclusions, authorization attributes, provenance, or lifecycle status. SQLite supplies those fields without loading a large JSON object and supports deterministic indexed queries.

For each code system the deployable unit is therefore:

```text
<system>.faiss       # immutable vectors
<system>.sqlite      # immutable metadata and rules
manifest.json        # version, hashes, model revision, dimensions, build provenance
```

## 5. Proposed repository structure

```text
src/medexa/
  application/
    clinical_span_service.py
    code_candidate_service.py
    regional_code_validation_service.py
  domain/
    clinical_span.py
    code_candidate.py
    code_suggestion.py
    trigger_signal.py
  ports/
    clinical_span_extractor.py
    embedding_provider.py
    vector_index.py
    code_catalogue.py
    code_validator.py
  adapters/
    nlp/gliner_span_extractor.py
    embeddings/bge_m3.py
    vector/faiss_index.py
    catalogue/sqlite_catalogue.py
    aws/s3_codepack_repository.py
  regions/
    sa/
      rules/sbs_code_validator.py
      rules/icd10am_code_validator.py
      loaders/sa_codepack_loader.py
    us/
      # Existing CPT/NCCI behavior retained during migration
    ae/
      # Future DHA/DOH/MOHAP catalogue and validators

scripts/
  build_codepack.py
  validate_codepack.py
  publish_codepack.py

tests/
  nlp/
  retrieval/
  regions/sa/
  security/
```

Core/application code depends only on protocols and domain types. Transformers, FAISS, SQLite, boto3, and Bedrock remain replaceable adapters. `ServiceContainer` composes implementations; domain logic must not import AWS or model libraries.

## 6. Domain contracts

Use frozen dataclasses or Pydantic models at boundaries. Do not pass loosely structured dictionaries through Path A.

```python
@dataclass(frozen=True)
class TranscriptChunk:
    session_id: str
    sequence: int
    source_text: str
    normalized_text: str
    language: str
    speaker: str | None
    started_at_ms: int
    ended_at_ms: int

@dataclass(frozen=True)
class ClinicalSpan:
    text: str
    normalized_text: str
    label: str
    start: int
    end: int
    confidence: float
    assertion: Literal["present", "negated", "planned", "historical", "uncertain"]

@dataclass(frozen=True)
class CodeCandidate:
    code_system: str
    code: str
    vector_id: int
    retrieval_score: float
    description_ar: str | None
    description_en: str
    source_version: str

@dataclass(frozen=True)
class CodeSuggestion:
    candidate: CodeCandidate
    evidence_text: str
    evidence_start: int
    evidence_end: int
    validation_reasons: tuple[str, ...]
    confidence_band: Literal["high", "review", "insufficient"]
    requires_clinician_review: bool = True
```

### Required ports

```python
class ClinicalSpanExtractorPort(Protocol):
    def extract(self, text: str, *, language: str) -> list[ClinicalSpan]: ...

class EmbeddingProviderPort(Protocol):
    def embed_queries(self, texts: Sequence[str]) -> NDArray[np.float32]: ...

class VectorIndexPort(Protocol):
    def search(self, vectors: NDArray[np.float32], *, top_k: int) -> list[list[VectorHit]]: ...

class CodeCataloguePort(Protocol):
    def get_many(self, vector_ids: Sequence[int]) -> list[CatalogueEntry]: ...

class CodeValidatorPort(Protocol):
    def validate(self, candidate: CatalogueEntry, evidence: ClinicalSpan, context: ValidationContext) -> ValidationResult: ...
```

Every adapter must be safe for concurrent reads. Model and index objects are initialized once per process, not per chunk.

## 7. Code-pack design

### 7.1 SQLite schema

```sql
CREATE TABLE code_entry (
    vector_id          INTEGER PRIMARY KEY,
    code_system        TEXT NOT NULL,
    code               TEXT NOT NULL,
    description_en     TEXT NOT NULL,
    description_ar     TEXT,
    chapter            TEXT,
    block_code         TEXT,
    service_type       TEXT,
    encounter_type     TEXT,
    active             INTEGER NOT NULL CHECK (active IN (0, 1)),
    effective_from     TEXT NOT NULL,
    effective_to       TEXT,
    source_version     TEXT NOT NULL,
    source_uri         TEXT NOT NULL,
    source_checksum    TEXT NOT NULL,
    UNIQUE(code_system, code, source_version)
);

CREATE TABLE code_alias (
    code_system        TEXT NOT NULL,
    code               TEXT NOT NULL,
    language           TEXT NOT NULL,
    alias               TEXT NOT NULL,
    provenance         TEXT NOT NULL,
    clinically_reviewed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (code_system, code, language, alias)
);

CREATE TABLE code_rule (
    rule_id             TEXT PRIMARY KEY,
    code_system         TEXT NOT NULL,
    code                TEXT,
    rule_type           TEXT NOT NULL,
    rule_payload_json   TEXT NOT NULL,
    source_uri          TEXT NOT NULL,
    source_version      TEXT NOT NULL
);

CREATE INDEX idx_code_entry_lookup ON code_entry(code_system, code, active);
CREATE INDEX idx_code_entry_dates ON code_entry(code_system, effective_from, effective_to);
```

SQLite is opened using a read-only URI, immutable mode where supported, a short busy timeout, and one connection per request/thread or a controlled pool. Runtime code never modifies a deployed catalogue.

### 7.2 S3 layout

```text
s3://<private-codepack-bucket>/codepacks/
  sa/
    2026-01-01/
      sbs.faiss
      sbs.sqlite
      icd10am.faiss
      icd10am.sqlite
      manifest.json
  us/
    2026-Q3/
      ...
  ae/
    future-version/
      ...
```

The S3 bucket must have Block Public Access enabled, versioning, SSE-KMS, least-privilege bucket policies, CloudTrail data events where required by the threat/risk assessment, and lifecycle rules for retired packs. Catalogue files contain no PHI.

### 7.3 Manifest contract

```json
{
  "schema_version": 1,
  "billing_region": "SA",
  "pack_version": "2026-01-01",
  "embedding_model": "BAAI/bge-m3",
  "embedding_model_revision": "<immutable-commit>",
  "embedding_dimension": 1024,
  "normalization_version": "ar-v1",
  "source_versions": {"SBS": "V3", "ICD10AM": "approved-release"},
  "artifacts": [{"name": "sbs.faiss", "sha256": "...", "bytes": 0}],
  "built_at": "2026-07-21T00:00:00Z",
  "build_id": "...",
  "approved_by": ["clinical-coding-owner", "security-owner"]
}
```

The loader rejects a pack if the schema, model revision, vector dimension, checksum, region, effective date, signature/approval, or source version does not match the deployment policy.

## 8. Offline code-pack build pipeline

This is a controlled release process, not an application-startup task.

1. **Acquire sources:** import only official, contractually authorized SBS, ICD-10-AM, CPT/HCPCS and regional rules.
2. **Record rights:** store licence/redistribution restrictions and allowed deployment scope outside the runtime artefact.
3. **Parse:** map source columns into canonical records; reject missing code, description, status, effective date, or provenance.
4. **Normalize:** apply versioned English and Arabic normalization without altering the original description.
5. **Add aliases:** import official Arabic text first; machine-generated aliases remain `clinically_reviewed=0` and cannot receive the same trust weight as reviewed aliases.
6. **Embed:** embed descriptions and approved aliases in batches using the pinned BGE-M3 revision.
7. **Index:** L2-normalize vectors and build an exact inner-product FAISS index.
8. **Persist metadata:** generate SQLite in one transaction; run `PRAGMA integrity_check` and foreign-key checks.
9. **Validate alignment:** verify every FAISS vector ID maps to exactly one active or historically valid metadata record.
10. **Evaluate:** run the approved bilingual retrieval suite and regional rule suite.
11. **Sign and publish:** generate hashes, approval metadata and immutable S3 version.
12. **Promote atomically:** update a small `current.json` pointer only after all gates pass. Never overwrite an active pack in place.

## 9. Runtime loading and caching

At process cold start:

1. resolve the required regional pack from `RegionRegistry`;
2. fetch `current.json` and `manifest.json` from S3;
3. compare the version with the local cache;
4. download missing artifacts to a versioned temporary directory;
5. verify SHA-256 before opening any artifact;
6. load all files into a new immutable `CodePackSnapshot`;
7. run readiness self-checks; and
8. atomically swap the snapshot reference.

Concurrent requests keep using the previous snapshot until the new snapshot is completely ready. Never expose a partially downloaded index. Use a process-level single-flight lock so simultaneous cold requests do not download the same pack repeatedly.

On failure, fail closed for new coding suggestions and keep the last verified snapshot if policy permits. Health checks report version and readiness but never bucket names, credentials, PHI, or internal stack traces.

## 10. Arabic ingestion and normalization

Amazon Transcribe `ar-SA` produces the source transcript. Each chunk stores:

- original Arabic text;
- normalized Arabic text;
- stable sequence number;
- speaker attribution when available;
- start/end timestamps;
- STT confidence where available; and
- language/provider metadata.

Normalization may remove diacritics/tatweel, normalize Unicode and whitespace, standardize Arabic/Western digits, and apply reviewed abbreviation mappings. It must retain an offset map to the original text so every suggestion cites exact evidence.

Do not aggressively stem medical terms. Do not silently translate. Mixed Arabic/English medical phrases remain mixed and are passed to the multilingual extractor/retriever.

Streaming partials are buffered until a stable boundary or bounded timeout. Only finalized segments create durable clinical events; partial hypotheses may update ephemeral UI text but must not create billable suggestions.

## 11. Path A implementation

### 11.1 Processing stages

1. **Extract spans:** GLiNER identifies configured clinical labels.
2. **Resolve assertion:** deterministic Arabic/English negation, uncertainty, temporality, and planned/performed rules annotate each span.
3. **Route catalogue:** symptoms/diagnoses search ICD-10-AM; performed interventions search SBS; US sessions remain on the existing CPT/ICD-10-CM route.
4. **Embed spans:** embed only relevant, bounded spans with nearby disambiguating context—not the entire conversation.
5. **Retrieve:** FAISS returns `top_k` candidates. `top_k` is configuration, initially 10.
6. **Hydrate:** SQLite resolves metadata in one parameterized query.
7. **Validate:** regional validators apply code status, effective date, setting, evidence, assertion, pre-authorization, coverage, exclusions and documentation requirements.
8. **Rank:** deterministic feature weights combine exact alias match, dense similarity, reviewed-Arabic alias match, rule satisfaction and ambiguity margin.
9. **Decide:** emit a suggestion, review-required candidate set, or abstention.
10. **Audit:** store pack version, model revision, rule IDs, evidence offsets, scores and decision reasons.

### 11.2 Safety rules

- Negated, historical-only, hypothetical and planned procedures are never treated as performed services.
- Diagnosis retrieval never proves a diagnosis; it creates a clinician-review candidate.
- Low STT confidence lowers or blocks the suggestion confidence band.
- Candidates outside the encounter date/effective window are rejected.
- A high vector score cannot override failed authorization or deterministic rules.
- A close top-1/top-2 margin produces ambiguity, not an arbitrary winner.
- Missing regional catalogue or validator means Path A fails closed for that code system.
- Every output contains source system/version and original-language evidence.

### 11.3 Initial performance objectives

- Warm Path A processing, excluding STT: p95 <= 500 ms on the selected production CPU target.
- No per-chunk S3 access after a verified pack is loaded.
- No per-chunk model initialization.
- Bounded transcript/span length, candidate count and memory allocation.
- Load tests must demonstrate behavior under the expected concurrent-session envelope before establishing an SLA.

## 12. Path B implementation

GLiNER is a signal producer, not the final gate. Existing `PathBTriggerEvaluator` remains the authoritative deterministic gate.

### 12.1 Trigger sources

- new symptom or meaningful symptom change;
- new performed intervention;
- body-region change;
- high-severity Path A alert;
- documentation gap;
- diagnosis/procedure mismatch;
- authorization or eligibility conflict;
- ambiguous Path A candidates requiring clarification;
- clinician explicit request; and
- configured time/state milestones.

Greetings, unchanged/repeated content, low-confidence fragments, background speech and already-handled events do not trigger Path B.

### 12.2 Anti-spam and concurrency controls

- idempotency key: `session_id + trigger_rule_id + semantic_event_key`;
- per-rule cooldown and maximum fires per session;
- global debounce;
- single in-flight Path B request per session unless a critical safety rule explicitly supersedes it;
- bounded queue with backpressure and dead-letter handling;
- optimistic locking/compare-and-swap when persisting Path A and Path B concurrently;
- retry only transient errors using exponential backoff with jitter;
- no retry for invalid input, policy rejection or guardrail rejection; and
- circuit breaker and no-op fallback when Bedrock is unavailable.

### 12.3 Minimum-necessary Bedrock context

The Path B context builder sends only information necessary for the selected trigger:

- bounded recent transcript window;
- original Arabic evidence relevant to the trigger;
- language and region;
- clinician-approved session facts;
- relevant Path A alerts, explicitly marked non-overridable; and
- the requested Arabic/English output language.

The prompt must require concise professional Arabic when `output_language=ar`, prohibit billing authority and automatic submission, request uncertainty disclosure, and prohibit facts unsupported by supplied evidence.

Before enabling Bedrock with PHI, verify the precise model, region, service configuration, logging policy, retention behavior, contractual coverage and required agreements. Do not assume that general AWS eligibility makes every model/configuration approved.

## 13. Arabic and English output

Domain results remain language-neutral. The API returns stable identifiers and localized presentation fields:

```json
{
  "eventType": "documentation_gap",
  "codeSystem": "SBS",
  "code": "<code>",
  "descriptionAr": "<approved Arabic description>",
  "descriptionEn": "<official English description>",
  "evidence": {"language": "ar", "text": "<original Arabic span>"},
  "messageKey": "path_a.authorization_review_required",
  "requiresClinicianReview": true
}
```

Path A messages use reviewed localization templates, not LLM translation. Path B may generate Arabic prose under guardrails. The frontend uses RTL layout for Arabic while preserving codes, identifiers and numbers without semantic alteration.

## 14. Security and privacy architecture

### 14.1 Data classification

| Data | Classification | Storage policy |
|---|---|---|
| Audio and transcripts | Restricted health data/ePHI | Encrypted, short retention, access-controlled |
| Session state and outputs | Restricted health data/ePHI | Encrypted, tenant- and role-scoped |
| Audit records | Sensitive security/compliance data | Append-only/tamper-evident, access-controlled |
| Code packs | Internal/licensed terminology; no PHI | Private S3, encrypted, versioned |
| Metrics | Non-PHI operational data | Strict label allow-list |

### 14.2 Required controls

- TLS 1.2+ in transit and KMS-backed encryption at rest.
- Separate KMS keys and IAM roles by environment and data class where justified by risk analysis.
- Least privilege, short-lived AWS credentials, no secrets in `.env` in hosted environments, and automatic secret rotation where supported.
- Unique user identity, MFA for privileged access, RBAC/ABAC, tenant isolation and periodic access review.
- S3 Block Public Access, bucket-owner-enforced object ownership and deny-unencrypted-transport policies.
- Private networking/VPC endpoints where supported and required by the approved architecture.
- Append-only security/audit events with integrity protection and documented retention.
- Central incident detection, alerting, breach-response runbooks and evidence preservation.
- Software composition analysis, secret scanning, SAST, dependency pinning, SBOM and signed container images.
- Model files pinned by revision and checksum; disallow runtime download from arbitrary public repositories in production.
- PHI-safe errors: external responses use stable error codes and request IDs; stack traces stay in protected internal logging.
- Backup, tested restoration, disaster recovery objectives and deletion workflows.
- Data retention per purpose and jurisdiction; temporary Transcribe audio is automatically deleted after processing unless a documented lawful purpose requires retention.

## 15. Compliance-by-design matrix

### 15.1 Saudi Arabia

The Saudi PDPL treats health information as sensitive data. Its implementing regulation requires appropriate organizational, technical and administrative protection; documented stages and accountable persons; separation of duties/access levels; processor obligations; and processing limited to what is necessary. Engineering must therefore implement data minimization, records of processing, purpose/retention controls, role-scoped access, processor contracts, auditability, data-subject workflows and privacy-impact assessment support.

The deployment must also map applicable NCA Essential, Cloud and Data Cybersecurity Controls and health/insurance requirements from the Ministry of Health, Saudi Health Council and Council of Health Insurance. Data residency and cross-border transfer are legal/compliance decision gates. Do not assume that deploying in Bahrain/UAE or using a global AI endpoint is acceptable for Saudi health data.

Production KSA release gates:

- approved data-flow map and privacy impact assessment;
- documented controller/processor roles and contracts;
- approved legal basis/purpose and consent handling where applicable;
- approved retention/deletion schedule;
- approved cross-border/data-localization assessment;
- approved cloud service, region and subprocessors;
- NCA control mapping and evidence;
- SBS/ICD-10-AM terminology rights and current versions;
- NPHIES/payer conformance testing; and
- Saudi clinical-coder sign-off on retrieval and deterministic rules.

### 15.2 United States / HIPAA

For HIPAA-regulated deployments, execute required Business Associate Agreements with every entity that creates, receives, maintains or transmits ePHI, including applicable cloud/subcontractor relationships. Perform and document risk analysis/risk management; enforce minimum necessary access; implement administrative, physical and technical safeguards; maintain audit controls, authentication, integrity, transmission security, incident/breach processes, contingency planning and availability.

HIPAA is not achieved by encryption or an “AWS HIPAA eligible” label alone. Each enabled service, region, model, log destination and subcontractor must be within the approved BAA and system risk assessment.

US production release gates additionally include CPT licensing verification, CMS/NCCI source/version controls, clinician review and no automatic claim submission.

### 15.3 UAE future readiness

UAE expansion must resolve federal health ICT/data rules, Federal Decree-Law No. 45 of 2021, health-data transfer restrictions, and regulator-specific requirements. Dubai integrations must map DHA/NABIDH policies including health-data protection/confidentiality, identity, access control, audit, incident/breach management, data classification, interoperability/data exchange and AI policy. Abu Dhabi and federal/MOHAP implementations require separate DOH/Malaffi or federal assessments rather than copying Dubai controls.

The UAE bundle must keep emirate/provider routing explicit:

```text
AE + DHA   -> DHA/eClaimLink policies and adapters
AE + DOH   -> DOH/Shafafiya/Malaffi policies and adapters
AE + MOHAP -> federal/MOHAP/payer-specific policies and adapters
```

No UAE production traffic is enabled until its regulator, hosting location, health-data transfer position, terminology, retention, access and interoperability requirements are approved.

## 16. Observability without PHI leakage

### Metrics

- transcript chunks accepted/rejected by region and language;
- GLiNER/model latency and error rate;
- Path A retrieval/validation/abstention counts;
- top-k retrieval latency and candidate-margin distribution;
- Path B triggers requested, suppressed, dispatched and completed;
- Bedrock latency, guardrail rejection and fallback counts;
- code-pack version/readiness/checksum failures; and
- queue depth, retry, dead-letter and optimistic-lock conflict counts.

Never use transcript, patient, clinician, member, authorization or free-text values as metric labels.

### Structured logs

Allow-list fields such as request ID, pseudonymous session correlation ID, region, language, component, rule ID, code-pack version, latency and outcome. Do not log prompt bodies, raw transcripts, model inputs/outputs, access tokens, patient identifiers or full exception payloads.

## 17. Testing and quality gates

No model training dataset is required for the MVP, but an evaluation set is mandatory for any accuracy claim.

### Automated tests

- Unit tests for Arabic normalization, offset preservation, assertion/negation, routing and validation.
- Property-based tests for normalization idempotence, bounds, Unicode safety and deterministic ranking.
- Contract tests for every port/adapter and API schema.
- Code-pack tests for checksums, vector/metadata one-to-one alignment, schema compatibility and effective dates.
- Golden tests for existing US Path A behavior to prevent regional regression.
- KSA tests for SBS/ICD routing, authorization, ambiguity, abstention and Arabic localization.
- Path B tests for idempotency, debounce, cooldown, concurrency, retry and circuit breaker behavior.
- Security tests for authorization, tenant isolation, PHI logging, malformed model/index files, path traversal and prompt-injection boundaries.
- Load/soak tests using synthetic, non-PHI sessions.
- Failure-injection tests for S3, index corruption, model timeout, Bedrock timeout and stale catalogue versions.

### Clinical evaluation

Create a version-controlled, de-identified or synthetic bilingual evaluation suite approved for its intended use. It is evaluation data, not necessarily training data. It must cover formal Arabic, Saudi dialect, mixed Arabic/English, STT errors, negation, historical/planned/performed activities, ambiguity and no-code cases.

Measure at minimum:

- clinical span precision/recall/F1;
- candidate Recall@1, Recall@5 and Recall@10;
- validated suggestion precision;
- unsafe false-positive rate;
- abstention rate and correctness;
- Path B trigger precision/recall;
- Bedrock calls per session; and
- Arabic output clinician acceptance.

Thresholds are approved by the clinical-safety owner before launch. Optimize for safe precision and appropriate abstention, not maximum suggestion volume.

## 18. Delivery phases

### Phase 0 — governance and source readiness

- Confirm intended use, clinical responsibility and prohibited automation.
- Approve SBS/ICD-10-AM/CPT rights and source versions.
- Complete data-flow, privacy, threat and regional hosting assessments.
- Define evaluation protocol and acceptance thresholds.

**Exit:** legal/privacy/security/clinical owners approve a non-production proof of concept.

### Phase 1 — code-pack platform

- Implement SQLite schema, build/validate/publish scripts and manifest.
- Implement S3 repository, checksum validation, local cache and atomic snapshot loading.
- Add health/readiness reporting and rollback.

**Exit:** deterministic reproducible pack build; corrupted/incompatible packs fail closed.

### Phase 2 — Arabic NLP boundary

- Implement lossless Arabic normalization and offsets.
- Add GLiNER adapter behind `ClinicalSpanExtractorPort`.
- Add assertion/negation/planned/performed resolution.
- Add model revision/checksum controls and performance benchmark.

**Exit:** target Arabic extraction evaluation meets approved threshold; existing US tests remain green.

### Phase 3 — KSA Path A retrieval

- Implement BGE-M3, FAISS and SQLite adapters.
- Route procedure spans to SBS and diagnosis/symptom spans to ICD-10-AM.
- Implement Saudi deterministic validators, confidence bands and abstention.
- Add Arabic/English structured API output and evidence citations.

**Exit:** retrieval and validated-suggestion metrics meet approved clinical-safety thresholds with zero LLM calls in Path A.

### Phase 4 — Path B integration

- Convert extracted changes and Path A outcomes to typed domain events.
- Extend trigger configuration with bilingual/semantic event keys.
- Enforce dedupe, debounce, cooldown, maximum fires and single-flight behavior.
- Add minimum-necessary Bedrock context and Arabic guardrailed output.

**Exit:** trigger evaluation meets threshold and Bedrock call budget without affecting Path A latency.

### Phase 5 — AWS production hardening

- Deploy private, encrypted, least-privilege infrastructure as code.
- Complete load, resilience, backup/restore and incident-response exercises.
- Complete KSA compliance gates and production risk acceptance.
- Use shadow mode before exposing suggestions.

**Exit:** signed production-readiness review.

### Phase 6 — UAE extension

- Add regulator-specific catalogue, adapters and validators to the AE region bundle.
- Complete UAE federal and emirate-specific legal/compliance assessment.
- Build UAE-specific evaluation and conformance suites.

**Exit:** independent UAE release approval; no assumption of KSA equivalence.

## 19. Deployment and rollback

Release progressively:

1. offline benchmark;
2. developer environment using synthetic data;
3. shadow mode with no UI suggestions;
4. clinician-only pilot with explicit experimental labeling;
5. limited production cohort;
6. monitored expansion.

Feature flags:

```text
MEDEXA_ARABIC_NLP_ENABLED
MEDEXA_SA_VECTOR_RETRIEVAL_ENABLED
MEDEXA_PATH_B_SEMANTIC_SIGNALS_ENABLED
MEDEXA_CODEPACK_VERSION_SA
MEDEXA_ARABIC_OUTPUT_ENABLED
```

Rollback must independently disable Arabic NLP, vector retrieval and Path B semantic signals; restore the prior signed code-pack pointer; and leave core session capture available where safe. Rollback never deletes audit evidence needed for incident analysis.

## 20. Cost controls

- Build embeddings offline once per code-pack version.
- Load code packs once per warm process; never fetch S3 per transcript chunk.
- Batch span embeddings within a chunk.
- Use exact FAISS search for the small catalogue before introducing managed vector infrastructure.
- Gate Path B using deterministic domain events and enforce per-session budgets.
- Apply bounded transcript windows and model token limits.
- Separate S3 storage/request costs from model compute, Transcribe and Bedrock budgets.
- Configure AWS Budgets, anomaly detection and tagged cost allocation by environment/component.

## 21. Inputs required from Medexa owners

Engineering can implement the platform, but the following cannot be safely invented:

- official and legally usable SBS and ICD-10-AM files;
- current CPT/HCPCS/NCCI rights and sources for the US;
- approved Arabic descriptions/aliases or a workflow for clinical review;
- regional coding, pre-authorization and payer rules;
- Saudi clinical-coder ownership and acceptance thresholds;
- intended-use and clinical-risk classification;
- retention, consent/legal-basis, hosting, residency and cross-border decisions;
- approved AWS services/models/regions and required contracts; and
- UAE regulator/emirate scope when that rollout begins.

## 22. Definition of done

The implementation is complete only when:

- Path A contains no LLM dependency and fails safely;
- every code suggestion is reproducible from source evidence, pack version, model revision and rule IDs;
- original Arabic evidence and offsets are preserved;
- retrieval, validation and trigger metrics meet approved thresholds;
- existing US behavior has no material regression;
- Path B call rate and latency stay within approved budgets;
- Arabic UI/output is clinically reviewed and RTL-safe;
- access, audit, encryption, retention, deletion, backup and incident controls are tested;
- KSA production compliance gates are signed;
- rollback is tested; and
- runbooks, threat model, privacy impact assessment, SBOM and operational ownership are current.

## 23. Authoritative references

- [Saudi PDPL implementing regulation — Article 26 health-data controls](https://dgp.sdaia.gov.sa/wps/portal/pdp/knowledgecenter/details/PDPL2/)
- [Saudi PDPL controller/processor guidance](https://dgp.sdaia.gov.sa/wps/portal/pdp/knowledgecenter/details/PDPLCP/)
- [Saudi NCA Cloud Cybersecurity Controls](https://nca.gov.sa/en/regulatory-documents/controls-list/ccc/)
- [Saudi NCA control implementation guides](https://nca.gov.sa/en/regulatory-documents/guidelines-list/1368/)
- [HHS summary of the HIPAA Security Rule](https://www.hhs.gov/hipaa/for-professionals/security/laws-regulations/index.html)
- [HHS guidance on HIPAA and cloud computing](https://www.hhs.gov/hipaa/for-professionals/special-topics/health-information-technology/cloud-computing/index.html)
- [HHS Business Associate Agreement provisions](https://www.hhs.gov/hipaa/for-professionals/covered-entities/sample-business-associate-agreement-provisions/index.html)
- [DHA health-data policies and regulations](https://www.dha.gov.ae/en/licensing-regulations-Nabidh)
- [DHA Health Data Protection and Confidentiality Policy](https://www.dha.gov.ae/uploads/082022/Health%20Data%20Protection%20and%20Confidentiality%20Policy_EN2022810559.pdf)
- [Amazon Transcribe supported languages and Arabic features](https://docs.aws.amazon.com/transcribe/latest/dg/supported-languages.html)
- [BGE-M3 model card and licence](https://huggingface.co/BAAI/bge-m3)
- [GLiNER multilingual model card and licence](https://huggingface.co/urchade/gliner_multi-v2.1)

Regulatory sources and model/service capabilities change. Compliance owners must revalidate this reference set and all service/model configurations before each regional production release.
