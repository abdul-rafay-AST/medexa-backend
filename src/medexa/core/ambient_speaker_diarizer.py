"""Voice-first ambient diarization for two-party clinical sessions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import numpy as np

from medexa.core.speaker_role_classifier import SpeakerRole, SpeakerRoleClassifier
from medexa.core.voice_features import (
    VoiceFeatures,
    blend_pitch,
    extract_voice_features,
    joint_voice_distance,
)
from medexa.core.voice_fingerprint import AudioDecodeError
from medexa.schemas import SessionState

logger = logging.getLogger(__name__)

DiarizationMethod = Literal["voice", "text", "hybrid"]
CLUSTER_A = "voice_a"
CLUSTER_B = "voice_b"
NEW_SPEAKER_DISTANCE = 0.17
VOICE_MATCH_DISTANCE = 0.09
PITCH_NEW_SPEAKER_HZ = 22.0
PITCH_CHANGE_TURN_HZ = 28.0


@dataclass(frozen=True)
class AmbientDiarizationResult:
    role: SpeakerRole
    confidence: float
    method: DiarizationMethod
    voice_cluster: str | None = None
    voice_confidence: float = 0.0
    text_confidence: float = 0.0
    pitch_hz: float = 0.0


class AmbientSpeakerDiarizer:
    """Pitch + timbre clustering with locked voice→role mapping after enrollment."""

    def __init__(
        self,
        text_classifier: SpeakerRoleClassifier,
        *,
        centroid_alpha: float = 0.22,
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
        client_pitch_hz: float | None = None,
    ) -> AmbientDiarizationResult:
        text_result = self._text_classifier.classify(
            transcript,
            last_speaker=state.last_ambient_speaker,
        )
        try:
            features = extract_voice_features(audio, content_type)
        except (AudioDecodeError, ValueError) as exc:
            logger.info("ambient_voice_features_unavailable: %s", exc)
            pitch_flip = self._speaker_from_pitch_change(state, client_pitch_hz)
            if pitch_flip is not None:
                state.last_ambient_pitch_hz = client_pitch_hz or state.last_ambient_pitch_hz
                return AmbientDiarizationResult(
                    role=pitch_flip,
                    confidence=0.72,
                    method="voice",
                    voice_cluster=state.last_voice_cluster,
                    voice_confidence=0.72,
                    text_confidence=text_result.confidence,
                    pitch_hz=round(client_pitch_hz or 0.0, 1),
                )
            return AmbientDiarizationResult(
                role=text_result.role,
                confidence=text_result.confidence,
                method="text",
                text_confidence=text_result.confidence,
            )

        pitch_hz, pitch_confidence = blend_pitch(
            features.pitch_hz,
            features.pitch_confidence,
            client_pitch_hz,
        )
        cluster_id, voice_confidence = self._assign_voice_cluster(
            features,
            state,
            pitch_hz=pitch_hz,
        )
        state.last_voice_cluster = cluster_id
        state.last_ambient_pitch_hz = pitch_hz if pitch_hz > 0 else state.last_ambient_pitch_hz
        self._update_centroid(state, cluster_id, features, pitch_hz)

        role, method = self._resolve_role(
            cluster_id=cluster_id,
            text_result=text_result,
            state=state,
            voice_confidence=voice_confidence,
            pitch_confidence=pitch_confidence,
        )

        return AmbientDiarizationResult(
            role=role,
            confidence=self._blend_confidence(
                voice_confidence,
                text_result.confidence,
                weight_voice=0.82 if method == "voice" else 0.55,
            ),
            method=method,
            voice_cluster=cluster_id,
            voice_confidence=voice_confidence,
            text_confidence=text_result.confidence,
            pitch_hz=round(pitch_hz, 1),
        )

    def _assign_voice_cluster(
        self,
        features: VoiceFeatures,
        state: SessionState,
        *,
        pitch_hz: float,
    ) -> tuple[str, float]:
        centroids = state.ambient_voice_centroids
        if not centroids:
            return CLUSTER_A, 0.6

        if pitch_hz > 0 and len(state.ambient_voice_pitch_centroids) >= 2:
            by_pitch = sorted(
                state.ambient_voice_pitch_centroids.items(),
                key=lambda item: abs(item[1] - pitch_hz),
            )
            pitch_cluster, pitch_delta = by_pitch[0]
            if pitch_delta <= 45.0:
                second_delta = abs(by_pitch[1][1] - pitch_hz) if len(by_pitch) > 1 else 999.0
                margin = max(0.0, second_delta - pitch_delta)
                return pitch_cluster, min(0.96, 0.7 + margin / 80.0)

        ranked: list[tuple[str, float]] = []
        for cluster_id, vector in centroids.items():
            ref = VoiceFeatures(
                fingerprint=np.asarray(vector, dtype=np.float64),
                pitch_hz=state.ambient_voice_pitch_centroids.get(cluster_id, 0.0),
                pitch_confidence=0.8,
                spectral_centroid_hz=0.0,
                voiced_ratio=1.0,
            )
            ranked.append(
                (
                    cluster_id,
                    joint_voice_distance(features, ref, left_pitch=pitch_hz, right_pitch=ref.pitch_hz),
                )
            )
        ranked.sort(key=lambda item: item[1])
        best_id, best_distance = ranked[0]
        second_distance = ranked[1][1] if len(ranked) > 1 else 1.0
        margin = max(0.0, second_distance - best_distance)

        nearest_pitch = state.ambient_voice_pitch_centroids.get(best_id, 0.0)
        pitch_delta = abs(pitch_hz - nearest_pitch) if pitch_hz > 0 and nearest_pitch > 0 else 0.0

        if len(centroids) == 1:
            if best_distance > NEW_SPEAKER_DISTANCE or pitch_delta >= PITCH_NEW_SPEAKER_HZ:
                return CLUSTER_B, min(0.94, 0.62 + margin + min(0.2, pitch_delta / 120.0))

        if best_distance <= VOICE_MATCH_DISTANCE and pitch_delta < PITCH_NEW_SPEAKER_HZ:
            return best_id, min(0.97, 0.68 + margin * 2.2)

        if CLUSTER_B not in centroids and (
            best_distance > NEW_SPEAKER_DISTANCE or pitch_delta >= PITCH_NEW_SPEAKER_HZ
        ):
            return CLUSTER_B, min(0.92, 0.58 + margin)

        return best_id, min(0.9, 0.52 + margin * 1.8)

    def _resolve_role(
        self,
        *,
        cluster_id: str,
        text_result,
        state: SessionState,
        voice_confidence: float,
        pitch_confidence: float,
    ) -> tuple[SpeakerRole, DiarizationMethod]:
        mapped = state.ambient_voice_cluster_roles.get(cluster_id)
        if mapped is not None:
            return mapped, "voice"

        if text_result.confidence >= 0.6:
            role: SpeakerRole = text_result.role
            method: DiarizationMethod = "hybrid"
        elif state.last_ambient_speaker:
            role = "patient" if state.last_ambient_speaker == "therapist" else "therapist"
            method = "voice" if voice_confidence >= 0.65 else "hybrid"
        else:
            role = text_result.role
            method = "hybrid"

        state.ambient_voice_cluster_roles[cluster_id] = role
        self._ensure_distinct_roles(state)
        return state.ambient_voice_cluster_roles[cluster_id], method

    def _ensure_distinct_roles(self, state: SessionState) -> None:
        if CLUSTER_A not in state.ambient_voice_cluster_roles or CLUSTER_B not in state.ambient_voice_cluster_roles:
            return
        role_a = state.ambient_voice_cluster_roles[CLUSTER_A]
        role_b = state.ambient_voice_cluster_roles[CLUSTER_B]
        if role_a == role_b:
            state.ambient_voice_cluster_roles[CLUSTER_B] = (
                "patient" if role_a == "therapist" else "therapist"
            )

    def _update_centroid(
        self,
        state: SessionState,
        cluster_id: str,
        features: VoiceFeatures,
        pitch_hz: float,
    ) -> None:
        vector = features.fingerprint.astype(np.float64)
        existing = state.ambient_voice_centroids.get(cluster_id)
        if existing is None:
            state.ambient_voice_centroids[cluster_id] = [float(v) for v in vector]
            if pitch_hz > 0:
                state.ambient_voice_pitch_centroids[cluster_id] = float(pitch_hz)
            return

        current = np.asarray(existing, dtype=np.float64)
        updated = (1.0 - self._centroid_alpha) * current + self._centroid_alpha * vector
        norm = float(np.linalg.norm(updated)) or 1.0
        state.ambient_voice_centroids[cluster_id] = [float(v / norm) for v in updated]

        if pitch_hz > 0:
            prior = state.ambient_voice_pitch_centroids.get(cluster_id, pitch_hz)
            state.ambient_voice_pitch_centroids[cluster_id] = float(
                (1.0 - self._centroid_alpha) * prior + self._centroid_alpha * pitch_hz
            )

    @staticmethod
    def _blend_confidence(voice_confidence: float, text_confidence: float, *, weight_voice: float) -> float:
        weight_voice = min(1.0, max(0.0, weight_voice))
        blended = weight_voice * voice_confidence + (1.0 - weight_voice) * text_confidence
        return round(min(0.98, max(0.4, blended)), 3)

    @staticmethod
    def _speaker_from_pitch_change(state: SessionState, pitch_hz: float | None) -> SpeakerRole | None:
        if not pitch_hz or pitch_hz <= 0 or not state.last_ambient_pitch_hz:
            return None
        if abs(pitch_hz - state.last_ambient_pitch_hz) < PITCH_CHANGE_TURN_HZ:
            return None
        if not state.last_ambient_speaker:
            return None
        return "patient" if state.last_ambient_speaker == "therapist" else "therapist"
