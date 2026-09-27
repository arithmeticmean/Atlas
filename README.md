# Atlas

Self-hosted, source-grounded RAG over your own documents. One process serves
both a JSON API and a React UI; answers stream back with citations to the
passages they came from.

Atlas runs entirely on your machine: SQLite for metadata, LanceDB for chunk
vectors, the raw files on local disk, and your choice of embedding/answering
model — local Ollama by default, or any hosted provider (OpenAI, Anthropic, or
anything speaking the OpenAI API: Kimi, Groq, DeepSeek, …).

## Install

```bash
uv tool install atlas          # or: pipx install atlas
atlas init                     # pick providers/models, create the owner account
atlas                          # -> http://127.0.0.1:8000
```

From a checkout, build and install it yourself (see **Build the CLI** below).

`atlas init` is interactive; pass `--non-interactive` with the options from
`atlas init --help` to script it.

**Model names are free text** — whatever your provider calls them, not a menu
of a handful that would go stale. Before writing anything, `atlas init`
contacts both the embedding model and the chat model, so a typo, a missing API
key, an unpulled Ollama model or an unreachable endpoint fails right there:

```
── Checking providers ────────────────────────

  ✓ embedding: ollama/nomic-embed-text 768 dimensions
  ✗ llm: ollama/llama3.2 model not pulled
    Ollama is reachable but has not pulled 'llama3.2'. Run `ollama pull
    llama3.2`. Currently pulled: llama3.1, nomic-embed-text.

error: provider checks failed -- nothing was written.
```

A failed check leaves no instance directory at all — there is nothing to clean
up. Pass `--skip-checks` to configure a machine before its provider is running.

The embedding dimension reported on success is what gets recorded in the index
lock file; changing the embedding model later forces a full reindex.

Everything Atlas owns lives in one directory — **`ATLAS_HOME`, default
`~/.atlas`**:

```
~/.atlas/
  config.toml     providers, models, server bind   (safe to read or share)
  secrets.toml    API keys + token signing secret  (0600)
  atlas.db        SQLite: users, projects, document metadata, job queue
  lance/          LanceDB: chunk text + vectors
  blobs/          your documents, as uploaded
  logs/
```

Back it up, move it to another machine, or delete it — one directory, one
operation. Nothing is written relative to the directory you happened to launch
from, and `atlas serve` applies its own migrations at startup.

Any setting can be overridden per-run by an `ATLAS_`-prefixed environment
variable (`ATLAS_LLM_MODEL=gpt-4o atlas serve`). Run `atlas home` to see where
an instance lives and what it contains.

## Commands

| | |
|---|---|
| `atlas init` | Create an instance: config, database, owner account |
| `atlas` / `atlas serve` | Run the API + web UI (`--host`, `--port`, `--reload`) |
| `atlas build-web` | Build the web UI (a checkout only; `serve` does it for you) |
| `atlas migrate` | Apply pending migrations (startup does this too) |
| `atlas home` | Show the instance directory and its contents |
| `atlas version` | Print the installed version |

## Develop

```bash
uv sync             # install the project + dev tools
uv run atlas init   # once
uv run atlas        # run it
```

`uv run atlas` with no subcommand runs the server, and builds the web UI first
if `service/web` is missing — so a fresh clone is one command, not two. It is
skipped when the UI is already built, when npm is absent (the API then serves
headless), and for an installed wheel, which ships the UI as package data and
has no sources to build from. `--no-build` opts out; `atlas build-web` runs it
on its own.

For backend auto-reload use `uv run atlas serve --reload`.

With the default all-local configuration you also need Ollama running
(`ollama serve`) with the configured models pulled.

The UI's own dev server, with hot reload and an `/api` proxy to the above:

```bash
cd web && npm install && npm run dev       # -> http://localhost:5173
```

Checks:

```bash
uv run ruff check .
uv run mypy
uv run pytest
```

### Build the CLI

Three steps, in this order:

```bash
uv run atlas build-web                                         # 1
uv build --wheel                                               # 2
uv tool install --force ./dist/atlas-0.1.0-py3-none-any.whl    # 3
```

1. **Required for a wheel.** Vite writes the SPA into `service/web/`, which is
   gitignored build output; the wheel force-includes it. Skip this and the wheel
   ships without a UI, and an installed `atlas` serves nothing at `/` — it
   cannot build one, because a wheel has no `web/` sources. (`atlas serve` from
   a *checkout* builds it automatically; a wheel build cannot.) Installs npm
   dependencies first if they are missing. `python scripts/build_web.py` is the
   same thing without the CLI.
2. Hatchling force-includes `service/web/**` (see `artifacts` in
   `pyproject.toml`), alongside `alembic.ini` and the migrations.
3. Install from the **wheel path**, not from `.`. `uv tool install --force .`
   can silently reuse a cached wheel and leave you testing stale code. Do not
   reach for `--no-cache` instead — it re-downloads every dependency.

The build is Python rather than shell so it works on Windows too; the
implementation is `cli/webbuild.py`, shared by `atlas serve`, `atlas build-web`
and `scripts/build_web.py` so they cannot drift.

## Layout

```
service/         the FastAPI backend, importable as `service`
  api/           app factory, routes, request-scoped wiring
  core/          application services: auth, projects, documents, ingestion,
                 search, answer, connectors, worker
  config/        settings + ATLAS_HOME resolution
  ingest/        loaders, splitters, embeddings, pipeline
  storage/       ports (store/) and adapters (sql/, blob/, vector/)
  models/        domain dataclasses
  migrations/    Alembic, shipped inside the package
  web/           built SPA, emitted by vite (gitignored)
cli/             the `atlas` console script, importable as `cli`
web/             React + Vite source
docs/PLAN.md     roadmap
```
