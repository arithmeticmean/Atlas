from functools import lru_cache
from typing import Literal

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    # Relational store (storage/sql). Self-hosted default is SQLite; point at
    # postgresql+asyncpg://... to run on Postgres with no code changes.
    database_url: str = "sqlite+aiosqlite:///./data/atlas.db"
    sql_echo: bool = False

    # Vector store (storage/vector). Directory for the local LanceDB dataset.
    vector_path: str = "./data/lance"

    # Blob store (storage/blob). Directory holding raw uploaded document bytes.
    blob_path: str = "./data/blobs"

    # Ingestion (ingest/). Splitter sizing. The embedding dimension is NOT
    # configured here -- it is probed from the chosen model at startup and
    # recorded in the vector store's lock file (see embedding_index.py).
    vector_table: str = "chunks"
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # Model providers. Default is all-local Ollama, no API keys. To use a
    # hosted provider, change the *_provider line and supply its model + key.
    # Changing embedding_provider/embedding_model triggers an automatic
    # in-place reindex on next startup; the LLM can be changed freely.
    embedding_provider: Literal["ollama", "openai", "fake"] = "ollama"
    llm_provider: Literal["ollama", "anthropic", "openai"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    embedding_model: str = "nomic-embed-text"  # 768-dim
    # For provider=anthropic set e.g. "claude-sonnet-5"; openai e.g. "gpt-5".
    llm_model: str = "llama3.1"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    # LLM via any OpenAI-compatible API (OpenRouter, Moonshot/Kimi, Groq,
    # DeepSeek, Together, Azure, vLLM, …): keep llm_provider="openai" and set
    # these to the provider's endpoint + key. llm_api_key falls back to
    # openai_api_key when unset; llm_base_url None means api.openai.com.
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    # Used only by the 'fake' embedding provider (offline/tests).
    fake_embedding_dim: int = 768

    # First-run owner account (created once at startup if it doesn't exist).
    # Written by configure.py; the password is hashed at creation.
    owner_email: str | None = None
    owner_password: str | None = None

    # Frontend (optional). Directory of the built React SPA (Vite `dist/`)
    # that FastAPI serves at "/". A relative path resolves from the service
    # root, so the default points at a sibling `web/` app. When the directory
    # does not exist the API runs headless (dev uses the Vite dev server).
    frontend_dir: str = "../web/dist"

    # Auth (service/auth.py). JWTs are signed with jwt_secret using a symmetric
    # HMAC algorithm. The default below is for local development ONLY -- set
    # JWT_SECRET (env var / .env; field names map 1:1, no prefix) to a long
    # random value in production, or every issued token becomes forgeable.
    jwt_secret: str = "dev-only-insecure-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_minutes: int = 60 * 24 * 7  # 7 days
    # Invite links carry a role, not an identity; they are shareable, so give
    # them a usable lifetime rather than the access-token 15 minutes.
    invite_token_ttl_minutes: int = 60 * 24 * 3  # 3 days

    # Ingestion worker (service/worker.py). Polls the DB-backed job queue
    # (storage/sql/jobs.py) for queued documents and embeds them in the
    # background, off the request path.
    ingest_poll_interval_seconds: float = 1.0
    ingest_max_attempts: int = 3

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
