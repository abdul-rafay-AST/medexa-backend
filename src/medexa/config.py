import json
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class MedexaConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEDEXA_", env_file=".env", env_file_encoding="utf-8")

    config_dir: Path = Path("config")
    suggestion_cooldown_seconds: int = 120
    max_session_duration_minutes: int = 240
    use_sse: bool = True
    enable_action_suggestions: bool = True

    # API / CORS. Accepts either a JSON array (["http://a","http://b"]) or a
    # plain comma-separated string (http://a,http://b). NoDecode disables the
    # default JSON-only parsing so the validator below can handle both forms.
    cors_allow_origins: Annotated[list[str], NoDecode] = ["*"]

    # Server bind settings (used by scripts/run_api_server.py). Defaults are
    # deployment-friendly: bind all interfaces, port from the platform's $PORT.
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False

    # Logging (Phase 5)
    log_level: str = "INFO"

    # Storage (Phase 4). Defaults to in-memory so NO AWS account is needed
    # to run locally or deploy. Flip use_dynamodb=True (with AWS creds +
    # the optional `aws` extra installed) for staging/production persistence.
    use_dynamodb: bool = False
    dynamodb_table_name: str = "medexa-sessions"
    aws_region: str = "us-east-1"

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return ["*"]
            if text.startswith("["):
                return json.loads(text)
            return [origin.strip() for origin in text.split(",") if origin.strip()]
        return value


settings = MedexaConfig()
