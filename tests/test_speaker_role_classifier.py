from medexa.core.speaker_role_classifier import SpeakerRoleClassifier, format_labeled_utterance


def test_patient_symptom_language():
    clf = SpeakerRoleClassifier()
    result = clf.classify("My lower back hurts when I bend forward.")
    assert result.role == "patient"
    assert result.confidence >= 0.5


def test_therapist_treatment_language():
    clf = SpeakerRoleClassifier()
    result = clf.classify("Let's start therapeutic exercise for lumbar stretching.")
    assert result.role == "therapist"
    assert result.confidence >= 0.5


def test_turn_taking_on_ambiguous_chunk():
    clf = SpeakerRoleClassifier()
    first = clf.classify("Hmm.", last_speaker=None)
    second = clf.classify("Hmm.", last_speaker=first.role)
    assert first.role != second.role


def test_format_labeled_utterance():
    assert format_labeled_utterance("therapist", "ROM looks good") == "Therapist: ROM looks good"
    assert format_labeled_utterance("patient", "Patient: it hurts") == "Patient: it hurts"
