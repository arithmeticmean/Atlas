"""Application settings and where they come from.

Sources, highest precedence first:

1. **Environment variables**, prefixed ``ATLAS_`` (``ATLAS_LLM_MODEL``). The
   prefix is not decoration -- without it a bare ``DATABASE_URL`` exported for
   some unrelated project would silently become Atlas's database.
2. **``$ATLAS_HOME/secrets.toml``** -- API keys and the token-signing secret,
   written 0600 and kept out of the file you might paste into a bug report.
3. **``$ATLAS_HOME/config.toml``** -- everything else, written by
   ``atlas init``.
4. **Defaults below**, which resolve every path under ``ATLAS_HOME`` so an
   instance never depends on the directory the process started in.

Both TOML files are flat: one key per field, matching the field names here.
Neither has to exist -- an instance with no files at all runs on defaults,
which is what makes ``atlas init`` able to bootstrap itself.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from service.config import paths


class Settings(BaseSettings):
    # --- storage -----------------------------------------------------------
    # Every path defaults under ATLAS_HOME (default ~/.atlas). Point
    # database_url at postgresql+asyncpg://... to run on Postgres instead, with
    # no code changes.
    database_url: str = Field(default_factory=paths.database_url)
    sql_echo: bool = False
    vector_path: str = Field(
        default_factory=lambda: str(paths.vector_path())
    )
    blob_path: str = Field(default_factory=lambda: str(paths.blob_path()))

    # Applied automatically at startup so an installed instance never needs a
    # separate migration command. Set false to manage schema yourself.
    auto_migrate: bool = True

    # --- ingestion ---------------------------------------------------------
    # Splitter sizing. The embedding dimension is NOT configured here -- it is
    # probed from the chosen model at startup and recorded in the vector
    # store's lock file (see services/embedding_index.py).
    vector_table: str = "chunks"
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # --- retrieval ---------------------------------------------------------
    # How candidates are found. "hybrid" runs dense and full-text retrieval and
    # fuses them with reciprocal rank fusion, so an exact term can win where
    # the embedding is unhelpful; "vector" and "fts" isolate one leg.
    search_mode: Literal["hybrid", "vector", "fts"] = "hybrid"
    # Whether a model reads the candidates and reorders them. Costs one extra
    # model call, so it is on for answering -- which already costs a call, and
    # where ordering decides what the answer is built from -- and off for raw
    # search, which should stay a fast lookup. /search can opt in per request.
    rerank_answers: bool = True
    rerank_search: bool = False
    # How many candidates to retrieve before reranking. Reranking only
    # reorders what it is given, so this is the recall ceiling when it runs.
    rerank_candidates: int = 20

    # --- model providers ---------------------------------------------------
    # Default is all-local Ollama, no API keys. Changing embedding_provider or
    # embedding_model triggers an automatic in-place reindex on next startup;
    # the LLM can be changed freely.
    embedding_provider: Literal["ollama", "openai", "fake"] = "ollama"
    llm_provider: Literal["ollama", "anthropic", "openai"] = "ollama"
    # localhost, not a container hostname: Atlas runs natively and reaches
    # Ollama on the host. Override for a remote or containerised Ollama.
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

    # --- frontend ----------------------------------------------------------
    # The built React SPA, served at "/". Defaults to the copy inside the
    # installed package; a relative value resolves from the package directory.
    # When the directory is absent the API runs headless, which is the normal
    # state in development (the Vite dev server serves the UI instead).
    frontend_dir: str = "web"

    # --- server ------------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8000

    # --- auth --------------------------------------------------------------
    # JWTs are signed with jwt_secret (symmetric HMAC). `atlas init` generates
    # one into secrets.toml; the empty default exists only so Settings can be
    # constructed before an instance is initialized. Serving with it unset is
    # refused at startup -- every issued token would be forgeable.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_minutes: int = 60 * 24 * 7  # 7 days
    # Invite links carry a role, not an identity; they are shareable, so give
    # them a usable lifetime rather than the access-token 15 minutes.
    invite_token_ttl_minutes: int = 60 * 24 * 3  # 3 days

    # --- ingestion worker --------------------------------------------------
    # Polls the DB-backed job queue (storage/sql/jobs.py) for queued documents
    # and embeds them in the background, off the request path.
    ingest_poll_interval_seconds: float = 1.0
    ingest_max_attempts: int = 3

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Highest precedence first. The TOML files are read at *call* time, so
        ``reload_settings()`` after writing them picks up the new values."""
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(
                settings_cls, paths.secrets_file()
            ),
            TomlConfigSettingsSource(settings_cls, paths.config_file()),
        )

    def resolved_frontend_dir(self) -> Path:
        """``frontend_dir`` as an absolute path.

        A relative value resolves against the package directory (where the
        bundled SPA lives), not the working directory -- so it means the same
        thing no matter where the process was started.
        """
        frontend = Path(self.frontend_dir)
        if not frontend.is_absolute():
            frontend = Path(__file__).resolve().parents[1] / frontend
        return frontend.resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    """Re-read every source, and rebind the module-level ``settings``.

    Needed after ``atlas init`` writes the files the cached instance was built
    without, and after ``atlas serve`` records the address it actually bound.
    Clearing the cache is not enough on its own: ``from service.config import
    settings`` binds the *object*, so importers that ran earlier would keep the
    stale one. Modules imported after this call get the new instance.
    """
    global settings
    get_settings.cache_clear()
    settings = get_settings()
    return settings


settings = get_settings()
