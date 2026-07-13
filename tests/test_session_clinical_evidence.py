from medexa.api.dependencies import ServiceContainer
from medexa.application.documentation_service import DocumentationService
from medexa.application.session_clinical_evidence import SessionClinicalEvidenceBuilder
from medexa.application.session_context_builder import SessionContextBuilder
from medexa.adapters.bedrock.documentation_generator import RulesDocumentationGenerator
from medexa.core.clinical_transcript_extractor import extract_transcript_clinical_facts
from medexa.schemas import Alert, DetectedEntity, SessionState, Suggestion


SHOULDER_TRANSCRIPT = """
Doctor: Looks like shoulder flexion is limited to about 90 degrees today. External rotation is also restricted to around 15 degrees.
Doctor: I'm going to perform some grade three inferior and anterior joint mobilizations on the glenohumeral joint.
Doctor: I'll also do some soft tissue mobilization on the pectoralis minor and upper trapezius. We'll spend about 15 minutes doing this manual therapy.
Doctor: We are going to do some isometric external rotations with the yellow resistance band. Let's do 2 sets of 10.
Doctor: We'll follow this up with some wall walk exercises. We've spent about 15 minutes on these exercises today.
Patient: No, no tingling, just the stiffness and the pain right around the front of the shoulder.
Patient: What should I be doing at home?
Doctor: Keep doing the pendulum exercises we talked about last time.
Doctor: You did great today. The joint mobilization helped, but we still have adhesive capsulitis to work through.
"""


def test_shoulder_transcript_extracts_specific_interventions():
    facts = extract_transcript_clinical_facts(SHOULDER_TRANSCRIPT)
    assert any("90" in item for item in facts.rom_measurements)
    assert any("15" in item for item in facts.rom_measurements)
    assert facts.session_duration_minutes == 30
    assert len(facts.intervention_blocks) == 2
    assert facts.intervention_blocks[0].cpt_code == "97140"
    assert facts.intervention_blocks[1].cpt_code == "97110"
    assert any("isometric" in item.lower() for item in facts.exercise_details)
    assert any("mobilization" in item.lower() for item in facts.manual_therapy_details)
    assert facts.denies_radicular is True
    assert any("mmt" in gap.lower() for gap in facts.compliance_gaps)


def test_soap_enricher_injects_billing_and_intervention_specificity():
    container = ServiceContainer()
    state = SessionState(
        session_id="shoulder-1",
        patient_name="Sarah Example",
        transcript_text=SHOULDER_TRANSCRIPT,
    )
    state.detected_entities.extend(
        [
            DetectedEntity(
                matched_phrase="joint mobilizations",
                possible_cpt="97140",
                body_region="shoulder_right",
                source_chunk_id="c1",
            ),
            DetectedEntity(
                matched_phrase="therapeutic exercise",
                possible_cpt="97110",
                body_region="shoulder_right",
                source_chunk_id="c2",
            ),
        ]
    )
    state.suggestions.extend(
        [
            Suggestion(
                suggestion_id="s1",
                session_id="shoulder-1",
                source_chunk_id="c1",
                suggestion_type="cpt_apply",
                title="Manual Therapy",
                message="Manual therapy detected",
                cpt_code="97140",
                body_region="shoulder_right",
                status="applied",
            ),
            Suggestion(
                suggestion_id="s2",
                session_id="shoulder-1",
                source_chunk_id="c2",
                suggestion_type="cpt_apply",
                title="Therapeutic Exercise",
                message="Therapeutic exercise detected",
                cpt_code="97110",
                body_region="shoulder_right",
                status="applied",
            ),
        ]
    )
    state.alerts.append(
        Alert(
            alert_id="a1",
            session_id="shoulder-1",
            alert_type="ncci_conflict",
            severity="high",
            message="NCCI: 97140 + 97110 on shoulder_right — Modifier 59 may apply",
            cpt_codes=["97140", "97110"],
            body_region="shoulder_right",
        )
    )

    context = SessionContextBuilder(container.icd_loader).build(state)
    service = DocumentationService(RulesDocumentationGenerator(), icd_loader=container.icd_loader)
    result = service.generate(state, context)

    objective = result.soap.objective.observation_notes.lower()
    billing = result.soap.billing_documentation
    assert "97140" in " ".join(billing.cpt_summary)
    assert "97110" in " ".join(billing.cpt_summary)
    assert billing.total_session_minutes == 30
    assert any("mobilization" in block.lower() for block in billing.intervention_blocks)
    assert billing.ncci_alerts
    assert "manual therapy" in objective or "mobilization" in objective
    assert "isometric" in objective or "therapeutic exercise" in objective
    assert any("mmt" in gap.lower() for gap in billing.compliance_gaps)
    assert result.soap.assessment.primary_diagnosis_code in {"M75.01", "M75.00"}
    assert result.soap.billing_documentation.ncci_alerts
