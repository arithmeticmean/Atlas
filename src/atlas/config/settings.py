"""The shape of Atlas's configuration. See the package docstring."""

import os
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

# The prefix matters: a bare DATA_PATH or PORT exported for some other program
# must not silently configure Atlas.
_ENV_PREFIX = "ATLAS_"

SECRET_FIELDS = (
    "openai_api_key",
    "anthropic_api_key",
    "google_api_key",
    "llm_api_key",
    "embedding_api_key",
)


class BootstrapSettings(BaseSettings):
    """What Atlas needs from the environment before it can open its data."""

    model_config = SettingsConfigDict(env_prefix=_ENV_PREFIX, extra="ignore")

    data_path: Path = Field(default_factory=lambda: Path.home() / ".atlas")
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    master_key: SecretStr | None = None

    @field_validator("data_path")
    @classmethod
    def _absolute(cls, path: Path) -> Path:
        return Path(os.path.expandvars(path)).expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self.data_path / "db" / "atlas.db"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def vector_path(self) -> Path:
        return self.data_path / "vector_db"

    @property
    def documents_path(self) -> Path:
        return self.data_path / "documents"

    @property
    def master_key_path(self) -> Path:
        return self.data_path / "master.key"

    def create_directories(self) -> None:
        """Private to this user, because the master key lives inside."""
        self.data_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        for directory in (
            self.database_path.parent,
            self.vector_path,
            self.documents_path,
        ):
            directory.mkdir(exist_ok=True)


class InstanceSettings(BaseModel):
    """Everything an admin can change while Atlas runs."""

    # extra="ignore": a setting removed in a later version must not stop an
    # older database from loading.
    model_config = ConfigDict(frozen=True, extra="ignore")

    # Models. Changing the embedding model requires a full reindex.
    embedding_provider: Literal[
        "ollama", "openai", "google", "openai_compatible", "fake"
    ] = "ollama"
    embedding_model: str = Field(default="nomic-embed-text", min_length=1)
    llm_provider: Literal[
        "ollama", "openai", "anthropic", "google", "openai_compatible"
    ] = "ollama"
    llm_model: str = Field(default="llama3.1", min_length=1)
    # Reasoning before answering: better on hard questions, much slower.
    llm_thinking: bool = False
    ollama_base_url: str = "http://localhost:11434"
    # A custom endpoint for each model, with its own key. Chat and embeddings
    # can use different providers.
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    embedding_base_url: str | None = None
    embedding_api_key: SecretStr | None = None
    # Shared by chat and embeddings when no endpoint-specific key is set.
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    google_api_key: SecretStr | None = None
    fake_embedding_dim: int = Field(default=768, ge=1)  # tests and offline

    # Ingestion. Size changes apply to documents indexed afterwards.
    chunk_size: int = Field(default=1000, ge=1)
    chunk_overlap: int = Field(default=200, ge=0)
    ingest_poll_interval_seconds: float = Field(default=1.0, gt=0)
    ingest_max_attempts: int = Field(default=3, ge=1)

    max_upload_mb: int = Field(default=512, ge=1)

    # Answering.
    retrieval_k: int = Field(default=5, ge=1, le=50)
    chat_history_messages: int = Field(default=10, ge=0, le=100)

    # Sessions, in minutes.
    access_token_ttl_minutes: int = Field(default=15, ge=1)
    refresh_token_ttl_minutes: int = Field(default=60 * 24 * 7, ge=1)
    invite_token_ttl_minutes: int = Field(default=60 * 24 * 3, ge=1)

    @field_validator("chunk_overlap")
    @classmethod
    def _overlap_fits(cls, overlap: int, info: ValidationInfo) -> int:
        size = info.data.get("chunk_size")
        if size is not None and overlap >= size:
            raise ValueError("Must be smaller than the chunk size.")
        return overlap


class Settings(InstanceSettings):
    """One consistent snapshot, passed to whatever needs configuration."""

    vector_path: str
    vector_table: str = "chunks"
    host: str = "127.0.0.1"
    port: int = 8000
    jwt_secret: str = Field(repr=False)
    jwt_algorithm: str = "HS256"

    @classmethod
    def compose(
        cls,
        bootstrap: BootstrapSettings,
        instance: InstanceSettings,
        *,
        jwt_secret: str,
    ) -> Self:
        return cls(
            **dict(instance),
            vector_path=str(bootstrap.vector_path),
            host=bootstrap.host,
            port=bootstrap.port,
            jwt_secret=jwt_secret,
        )
