from datetime import UTC, datetime

from medexa.api.dependencies import ServiceContainer
from medexa.schemas import DetectedEntity, SessionState, TranscriptChunk


def test_ncci_alert_from_detected_entities_without_timers() -> None:
    container = ServiceContainer()
    runtime = container.runtime_for_region("US")
    state = SessionState(session_id="ncci-entities")
    chunk = TranscriptChunk(
        session_id="ncci-entities",
        chunk_id="c1",
        text="manual therapy and therapeutic exercise on the right shoulder",
        start_ts=0,
        end_ts=15,
        sequence=1,
    )
    state.detected_entities.extend(
        [
            DetectedEntity(
                matched_phrase="manual therapy",
                possible_cpt="97140",
                body_region="shoulder_right",
                source_chunk_id="c1",
            ),
            DetectedEntity(
                matched_phrase="therapeutic exercise",
                possible_cpt="97110",
                body_region="shoulder_right",
                source_chunk_id="c1",
            ),
        ]
    )
    runtime.path_a_processor.process(state, chunk, datetime.now(UTC))
    ncci_alerts = [a for a in state.alerts if a.alert_type == "ncci_conflict"]
    assert ncci_alerts
    assert "97140" in ncci_alerts[0].message
    assert "97110" in ncci_alerts[0].message
    billing_insights = [i for i in state.insights if i.type == "billing"]
    assert billing_insights
    assert billing_insights[0].status == "pending"
