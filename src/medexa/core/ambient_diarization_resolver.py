"""Hybrid ambient diarization: Deepgram STT + cross-chunk voice roles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from medexa.core.ambient_speaker_diarizer import AmbientDiarizationResult, AmbientSpeakerDiarizer
from medexa.core.deepgram_speaker_mapper import DeepgramSpeakerRoleMapper
from medexa.core.speaker_role_classifier import SpeakerRole
from medexa.schemas import SessionState
from medexa.services.transcription import TranscriptionResult, TranscriptSegment

DiarizationMethod = Literal["deepgram", "aws_transcribe", "voice", "text", "hybrid"]


@dataclass(frozen=True)
class ResolvedUtterance:
    speaker: SpeakerRole
    text: str
    confidence: float
    method: DiarizationMethod
    start_offset: float = 0.0
    end_offset: float = 0.0


@dataclass(frozen=True)
class ChunkDiarizationResult:
    """Per-upload diarization outcome for one ambient audio chunk."""

    primary_role: SpeakerRole
    confidence: float
    method: DiarizationMethod
    segments: list[TranscriptSegment]
    utterances: list[ResolvedUtterance]


class AmbientDiarizationResolver:
    """Combines Deepgram transcription with stable cross-chunk speaker roles.

    Deepgram speaker indices (0, 1, …) are only meaningful *within one audio
  file*. Each browser upload is a separate file, so reusing speaker 0 across
    chunks would label every clip as the same person. Voice clustering stays
    primary for cross-chunk turns; Deepgram diarization is used when multiple
    speakers appear inside the same chunk.
    """

    def __init__(
        self,
        *,
        voice_diarizer: AmbientSpeakerDiarizer,
        deepgram_mapper: DeepgramSpeakerRoleMapper,
    ) -> None:
        self._voice_diarizer = voice_diarizer
        self._deepgram_mapper = deepgram_mapper

    def resolve(
        self,
        *,
        audio: bytes,
        content_type: str | None,
        transcript: str,
        transcription: TranscriptionResult,
        state: SessionState,
        client_pitch_hz: float | None,
        chunk_start_ts: float,
        chunk_end_ts: float,
    ) -> ChunkDiarizationResult:
        segments = list(transcription.segments)
        distinct_speakers = {
            segment.speaker_id for segment in segments if segment.speaker_id is not None
        }
        multi_speaker_in_chunk = len(distinct_speakers) >= 2

        if multi_speaker_in_chunk:
            mapped = self._deepgram_mapper.resolve_within_chunk(
                segments=segments,
                full_transcript=transcript,
                last_speaker=state.last_ambient_speaker,
            )
            stt_method: DiarizationMethod = (
                "aws_transcribe"
                if transcription.provider == "aws_transcribe"
                else "deepgram"
            )
            utterances = [
                ResolvedUtterance(
                    speaker=segment.speaker_role or mapped.role,
                    text=segment.text.strip(),
                    confidence=mapped.confidence,
                    method=stt_method,
                    start_offset=segment.start,
                    end_offset=segment.end,
                )
                for segment in mapped.segments
                if segment.text.strip() and segment.speaker_role
            ]
            if not utterances:
                utterances = [
                    ResolvedUtterance(
                        speaker=mapped.role,
                        text=transcript,
                        confidence=mapped.confidence,
                        method=stt_method,
                    )
                ]
            return ChunkDiarizationResult(
                primary_role=utterances[-1].speaker,
                confidence=mapped.confidence,
                method=stt_method,
                segments=mapped.segments,
                utterances=utterances,
            )

        voice = self._voice_diarizer.classify(
            audio=audio,
            content_type=content_type,
            transcript=transcript,
            state=state,
            client_pitch_hz=client_pitch_hz,
        )
        method: DiarizationMethod = (
            "hybrid"
            if transcription.provider in {"deepgram", "aws_transcribe"}
            else voice.method
        )
        if not segments:
            segments = [
                TranscriptSegment(
                    start=0.0,
                    end=max(chunk_end_ts - chunk_start_ts, 0.0),
                    text=transcript,
                    speaker_role=voice.role,
                )
            ]
        else:
            segments = [
                segment.model_copy(update={"speaker_role": voice.role}) for segment in segments
            ]

        utterances = [
            ResolvedUtterance(
                speaker=voice.role,
                text=transcript,
                confidence=voice.confidence,
                method=method,
            )
        ]
        return ChunkDiarizationResult(
            primary_role=voice.role,
            confidence=voice.confidence,
            method=method,
            segments=segments,
            utterances=utterances,
        )
