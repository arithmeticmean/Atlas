# AGENTS.md

Guide for AI agents working in the Atlas codebase.

## What Atlas is

An installable, self-hosted RAG application. One FastAPI process serves a JSON
API under `/api` and the built React SPA at `/`. Documents are uploaded, queued,
chunked, embedded, and indexed in the background; search and answer read that
index back and stream cited answers.

**Not a library and not a dev-server project.** It installs as a wheel with one
console script (`atlas`) and keeps all state in one local directory. Any change
that reintroduces a dependency on the current working directory, on a repository
checkout, or on `python -m`/`uv run` as the entry point is a regression.

## Technology

- Python 3.11+, `uv` (not pip), `hatchling` build backend. One distribution
  named `atlas`, shipping two top-level packages: `service` and `cli`
- FastAPI + uvicorn; Typer for the CLI
- SQLAlchemy 2.0 async + Alembic; SQLite by default (`postgresql+asyncpg://`
  also works with no code change)
- LanceDB for chunks, via the **native async client** (not langchain's
  wrapper -- see the retrieval invariant below)
- langchain for loaders, embeddings, and chat models only

## Commands

```bash
uv sync                                    # install project + dev tools
uv run atlas init                          # create a local instance
uv run atlas                               # run it (builds the UI if missing)
uv run atlas serve --reload                # backend auto-reload
uv run ruff check .                        # lint (line-length 79)
uv run mypy                                # strict, must stay clean
uv run pytest
uv run atlas build-web && uv build         # release wheel, SPA included
```

## Layout

```
service/       the FastAPI backend (import service.*)
  api/         app.py (factory + lifespan), dependencies.py (composition
               root), routes/
  core/        application services -- the orchestration layer:
               auth, projects, document, ingestion, search, answer,
               connectors, connector_manager, worker, embedding_index,
               llm, bootstrap
  config/      config.py (Settings), paths.py (ATLAS_HOME resolution)
  ingest/      loaders, splitters, embeddings, pipeline
  storage/
    store/     ports (ABCs) -- depend on these, not adapters
    sql/       SQLAlchemy adapters, ORM models, migrate.py
    blob/      disk blob store
    lance/     native LanceDB ChunkIndex adapter
  models/      domain dataclasses
  migrations/  Alembic; alembic.ini sits at the service/ root
  web/         built SPA (generated, gitignored, force-included in the wheel)
cli/           main.py (commands), init.py (instance creation),
               preflight.py (provider checks), webbuild.py (UI build),
               _ui.py (ANSI)
web/           React + Vite source
```

Layering runs one way: `api` -> `core` -> `storage`/`ingest`. Nothing in `core`
imports `service.api`.

## Invariants

**State lives in `ATLAS_HOME`** (default `~/.atlas`). Resolve paths through
`service.config.paths`, never relative to the CWD and never relative to the
package. Settings defaults use `Field(default_factory=...)` so they follow
`ATLAS_HOME` at instantiation time.

**Nothing expensive or configuration-dependent at import time.** The engine
(`service/storage/sql/db.py`), the session factory, and the token codec
(`api/dependencies.py`) are all `@lru_cache` functions built on first use, so
`atlas init` can import the backend before an instance exists. CLI commands
import their dependencies *inside* the function body for the same reason — keep
`cli/main.py` import-light.

**Config precedence** is `ATLAS_`-prefixed env > `secrets.toml` > `config.toml` >
defaults. The prefix is load-bearing: without it a stray `DATABASE_URL` in the
shell would silently become Atlas's database. Secrets go in `secrets.toml`
(0600); `config.toml` must stay safe to paste into a bug report.

**Migrations run in-process** (`storage/sql/migrate.py`), from the copy of
`alembic.ini` + `migrations/` inside the package. An installed user has no
`alembic` on PATH — `uv tool install` exposes only the target package's own
entry points — so schema management can never be a shell step. `migrations/env.py`
must keep honouring an already-set `sqlalchemy.url` and must not reconfigure
logging when driven in-process.

**No barrel `__init__.py` files.** `service/__init__.py` and
`service/core/__init__.py` carry a docstring and nothing else. Python executes a
parent package before any submodule, so re-exports there put the whole service
layer -- and through it langchain, SQLAlchemy and numpy -- on the import path of
every leaf. A barrel in `service/__init__.py` made `atlas home` take 2.0s and
load numpy to print a directory path; without it that is 0.33s. Import from the
module that defines the name.

**Retrieval is hybrid, and the chunk index is Atlas's own port.** Not
langchain's `VectorStore`: its LanceDB wrapper embeds the query itself and
passes a single value to `tbl.search()`, while hybrid needs the query vector
*and* its raw text, so hybrid is unreachable through it. `storage/lance/` drives
LanceDB directly -- `query().nearest_to(v).nearest_to_text(q).rerank()` -- with
an explicit pyarrow schema (never inferred: the vector dim and nullability must
be stable) and a native FTS index on `text`. Don't reintroduce the wrapper.

**Scores are relevance: higher is better, always.** The three modes report on
incompatible scales (`_distance` ascending, `_score` and `_relevance_score`
descending), so `storage/lance/chunk_index.py` normalises direction before
anything leaves it. A caller cannot render a number whose direction depends on
a mode flag -- the UI's relevance bar depends on this.

**Two different rerank stages, don't conflate them.** RRF inside the index fuses
the dense and sparse rankings of a hybrid query, and is free. `core/rerank.py`
is a second stage that asks the *configured chat model* to reorder candidates --
one extra call, built on the existing provider rather than a cross-encoder,
because `sentence-transformers` would drag torch into a project whose point is
installing from one wheel. It must always degrade to the retrieval order, never
to an empty result.

**Chunk ids are deterministic** (`<document_id>:<chunk_index>`), and re-ingest
is delete-then-add. Random ids would accumulate duplicates on every re-index.

**Async everywhere** for I/O. All database access is async; blocking work
(loaders, splitters, LanceDB, Alembic) goes through `asyncio.to_thread`.

**Project isolation.** Every chunk carries `project_id`, and every search
pre-filters on it. Chunks share one LanceDB table, so this filter is the only
thing separating projects.

**Model names are never enumerated.** Providers are a closed set (each maps to
a branch in `build_embeddings` / `build_chat_model`); model names are free text.
`cli/preflight.py` validates a candidate `Settings` by making a real call to
each provider before `atlas init` writes anything, so a wrong name fails at init
rather than at the next `serve`. Both factories take an optional `Settings` so
a candidate config can be probed without being saved. Don't reintroduce model
menus.

**Never serve without a signing secret.** `jwt_secret` has an empty default
purely so `Settings()` can be constructed pre-init; `api/app.py` refuses to
start without one.

## Conventions

- SQLAlchemy 2.0 style: `Mapped[...]` / `mapped_column(...)`, `Base` from
  `service.storage.sql.db`
- Modern typing: `str | None`, `list[str]`
- Absolute imports from `service.*` / `cli.*`; relative only within a subpackage
- Application code depends on `service.storage.store` ports, so langchain imports
  stay inside `ingest/` and `storage/vector/`
- Docstrings explain *why*, not *what*; line length 79

## Adding things

**A setting:** add the field to `Settings` (use `default_factory` for anything
path-derived), then to `atlas init`'s writer if it should be persisted, and put
it in `secrets.toml` if it is a credential.

**A CLI command:** a function in `cli/main.py` with imports inside the body.

**A model:** define it under `storage/sql/models/`, export it from that
package's `__init__` so `migrations/env.py` sees the metadata, then
`uv run alembic -c service/alembic.ini revision --autogenerate -m "..."`.
Review the generated migration before committing.

**A loader:** one entry in `_LOADERS` in `ingest/loaders.py`, plus `_EXT_TO_MIME`
if the extension fallback should recognise it.

## Known gaps

- **No tests.** `tests/` holds only fixtures. `pytest-asyncio` and `httpx` are
  not in the dev group, so async/API tests cannot run yet.
- The FTS index is not rebuilt after writes (`num_unindexed_rows` grows).
  Correctness is unaffected -- LanceDB scans unindexed rows -- but a periodic
  `optimize()` in the worker is wanted before the corpus gets large.
- `ingest/loaders.py` imports `magic` at module scope, so a machine without
  the native libmagic fails at import rather than degrading to the mime and
  extension fallbacks that already exist.
- No `atlas doctor`, no logging to `logs/`, no systemd unit yet (roadmap
  steps 6-7).
