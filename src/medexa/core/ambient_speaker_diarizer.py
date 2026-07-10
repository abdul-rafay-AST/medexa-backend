"""Voice + clinical-text ambient diarization for mono microphone sessions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import numpy as np

from medexa.core.speaker_role_classifier import SpeakerRole, SpeakerRoleClassifier
from medexa.core.voice_fingerprint import AudioDecodeError, cosine_distance, extract_voice_fingerprint
from medexa.schemas import SessionState

logger = logging.getLogger(__name__)

DiarizationMethod = Literal["voice", "text", "hybrid"]
CLUSTER_A = "voice_a"
CLUSTER_B = "voice_b"
NEW_SPEAKER_DISTANCE = 0.12
VOICE_MATCH_DISTANCE = 0.08


@dataclass(frozen=True)
class AmbientDiarizationResult:
    role: SpeakerRole
    confidence: float
    method: DiarizationMethod
    voice_cluster: str | None = None
    voice_confidence: float = 0.0
    text_confidence: float = 0.0


class AmbientSpeakerDiarizer:
    """Cluster speakers by voice fingerprint, map clusters to patient/therapist roles."""

    def __init__(
        self,
        text_classifier: SpeakerRoleClassifier,
        *,
        centroid_alpha: float = 0.18,
    ) -> None:
        self._text_classifier = text_classifier
        self._centroid_alpha = centroid_alpha

    def classify(
        self,
        *,
        audio: bytes,
        content_type: str | None,
        transcript: str,
        state: SessionState,
    ) -> AmbientDiarizationResult:
        text_result = self._text_classifier.classify(
            transcript,
            last_speaker=state.last_ambient_speaker,
        )
        try:
            fingerprint = extract_voice_fingerprint(audio, content_type)
        except (AudioDecodeError, ValueError) as exc:
            logger.debug("ambient_voice_fingerprint_skipped: %s", exc)
            return AmbientDiarizationResult(
                role=text_result.role,
                confidence=text_result.confidence,
                method="text",
                text_confidence=text_result.confidence,
            )

        cluster_id, voice_confidence = self._assign_voice_cluster(fingerprint, state)
        state.last_voice_cluster = cluster_id
        self._update_centroid(state, cluster_id, fingerprint)

        mapped_role = state.ambient_voice_cluster_roles.get(cluster_id)
        if mapped_role is None:
            state.ambient_voice_cluster_roles[cluster_id] = text_result.role
            return AmbientDiarizationResult(
                role=text_result.role,
                confidence=self._blend_confidence(voice_confidence, text_result.confidence, weight_voice=0.35),
                method="hybrid" if text_result.confidence >= 0.55 else "text",
                voice_cluster=cluster_id,
                voice_confidence=voice_confidence,
                text_confidence=text_result.confidence,
            )

        if text_result.confidence >= 0.8 and mapped_role != text_result.role:
            state.ambient_voice_cluster_roles[cluster_id] = text_result.role
            final_role = text_result.role
            method: DiarizationMethod = "hybrid"
        elif text_result.confidence >= 0.65 and mapped_role == text_result.role:
            final_role = mapped_role
            method = "hybrid"
        else:
            final_role = mapped_role
            method = "voice"

        return AmbientDiarizationResult(
            role=final_role,
            confidence=self._blend_confidence(
                voice_confidence,
                text_result.confidence,
                weight_voice=0.7 if method == "voice" else 0.45,
            ),
            method=method,
            voice_cluster=cluster_id,
            voice_confidence=voice_confidence,
            text_confidence=text_result.confidence,
        )

    def _assign_voice_cluster(
        self,
        fingerprint: np.ndarray,
        state: SessionState,
    ) -> tuple[str, float]:
        centroids = state.ambient_voice_centroids
        if not centroids:
            return CLUSTER_A, 0.55

        ranked = sorted(
            ((cluster_id, cosine_distance(fingerprint, np.asarray(vector, dtype=np.float64)))
             for cluster_id, vector in centroids.items()),
            key=lambda item: item[1],
        )
        best_id, best_distance = ranked[0]
        second_distance = ranked[1][1] if len(ranked) > 1 else 1.0
        margin = max(0.0, second_distance - best_distance)

        if len(centroids) == 1 and best_distance > NEW_SPEAKER_DISTANCE:
            return CLUSTER_B, min(0.9, 0.55 + margin)

        if best_distance <= VOICE_MATCH_DISTANCE:
            confidence = min(0.96, 0.62 + margin * 2.5)
            return best_id, confidence

        if CLUSTER_B not in centroids and best_distance > NEW_SPEAKER_DISTANCE:
            return CLUSTER_B, min(0.88, 0.5 + margin)

        confidence = min(0.9, 0.5 + margin * 2.0)
        return best_id, confidence

    def _update_centroid(self, state: SessionState, cluster_id: str, fingerprint: np.ndarray) -> None:
        vector = fingerprint.astype(np.float64)
        existing = state.ambient_voice_centroids.get(cluster_id)
        if existing is None:
            state.ambient_voice_centroids[cluster_id] = [float(v) for v in vector]
            return
        current = np.asarray(existing, dtype=np.float64)
        updated = (1.0 - self._centroid_alpha) * current + self._centroid_alpha * vector
        norm = float(np.linalg.norm(updated)) or 1.0
        state.ambient_voice_centroids[cluster_id] = [float(v / norm) for v in updated]

    @staticmethod
    def _blend_confidence(voice_confidence: float, text_confidence: float, *, weight_voice: float) -> float:
        weight_voice = min(1.0, max(0.0, weight_voice))
        blended = weight_voice * voice_confidence + (1.0 - weight_voice) * text_confidence
        return round(min(0.98, max(0.35, blended)), 3)
