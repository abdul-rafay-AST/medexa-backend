from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class MedexaConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEDEXA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    config_dir: Path = Path("config")
    cpt_files_dir: Path = Path("MEDEXA CPT FILES")
    suggestion_cooldown_seconds: int = 120
    max_session_duration_minutes: int = 240
    use_sse: bool = True
    realtime_transport: Literal["sse", "websocket"] = "sse"
    enable_action_suggestions: bool = True

    cors_allow_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Path B — live assistant (rules path stays Path A only).
    path_b_enabled: bool = False
    path_b_provider: Literal["bedrock", "groq"] = "bedrock"
    path_b_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    path_b_interval_seconds: int = 20
    path_b_transcript_window_minutes: int = 10
    path_b_transcript_max_chunks: int = 24

    clinical_analyzer: Literal["rules", "bedrock"] = "rules"
    soap_generator: Literal["rules", "bedrock", "groq"] = "rules"
    summary_generator: Literal["rules", "bedrock", "groq"] = "rules"
    path_c_model_id: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"

    # Groq (temporary Path B/C + Whisper STT until Bedrock IAM is ready).
    groq_api_key: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_path_b_model_id: str = "llama-3.1-8b-instant"
    groq_path_c_model_id: str = "llama-3.3-70b-versatile"
    groq_whisper_model_id: str = "whisper-large-v3-turbo"

    transcription_provider: Literal["none", "aws_transcribe", "groq_whisper"] = "none"
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"
    transcribe_s3_bucket: str | None = None

    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False
    log_level: str = "INFO"

    use_dynamodb: bool = False
    session_persist_dir: Path | None = Path("data/sessions")
    dynamodb_table_name: str = "medexa-sessions"
    aws_region: str = "us-east-1"
    aws_environment: Literal["local", "staging", "prod"] = "staging"
    s3_bucket: str | None = None
    config_source: Literal["local", "s3"] = "local"

    @field_validator("*", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("realtime_transport", mode="before")
    @classmethod
    def _coerce_realtime_transport(cls, value: object) -> object:
        if value is None:
            return "sse"
        return value

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return ["*"]
            if text.startswith("["):
                import json

                return json.loads(text)
            return [origin.strip() for origin in text.split(",") if origin.strip()]
        return value


settings = MedexaConfig()
