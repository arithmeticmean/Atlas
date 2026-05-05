# Atlas — Roadmap to a Full Self-Hosted RAG Platform

Target: bring Atlas to feature parity with the reference project (`.ref` =
**OpenDocuments**, a TypeScript self-hosted RAG platform), in Python.

**Storage decision: LOCKED — SQLite + LanceDB.** Chunks live in LanceDB.
Hybrid search is done by LanceDB natively. Rationale and the one thing this
forces us to change are in §3.

---

## 1. What the reference is

OpenDocuments is a **self-hosted RAG platform** — not a library, not a chatbot.

```
packages/
  core     RAG engine, ingest, storage, auth, security, plugin runtime  (~5k LOC)
  server   Hono HTTP API + MCP server + embeddable widget
  cli      `opendocuments` — init/index/ask/search/doctor/backup/...
  web      React + Vite UI (chat, documents, collections, admin, health)
  client   TypeScript SDK
plugins/
  connector-*  github, notion, gdrive, s3, confluence, swagger, web-crawler, web-search
  parser-*     pdf, docx, xlsx, pptx, html, code, email, jupyter
  model-*      openai, anthropic, google, grok, ollama
```

Principles: **core-first** (CLI/server/web/SDK/MCP are thin shells),
**plugin-first** (connectors/parsers/models are swappable contracts),
**source-grounded** (every answer carries cited sources + confidence, verified
against those sources before return).

Its storage split is SQLite (metadata) + FTS5 (keyword) + LanceDB (vectors).
**Atlas collapses this to SQLite (metadata) + LanceDB (chunks: text + vector +
keyword index).** One fewer moving part than the reference.

Retrieval pipeline — the actual product:

```
query → intent classify → decompose → expand (HyDE / multi-query)
      → dense + sparse → RRF merge → metadata boost → parent-doc expansion
      → rerank → context-window fitting → generate → grounding check
      → answer + sources + confidence
```

Gated by profiles: `fast` / `balanced` / `precise` / `custom`.

---

## 2. What Atlas has today

~1,600 LOC / 40 files, plus ~815 LOC of parked work in `.bak/`. The hexagonal
ports/adapters architecture is genuinely good. But it is the plumbing, not the
product: **Atlas can ingest documents and never read them back.** No search
endpoint, no RAG engine, no LLM call anywhere.

### Working

| Area | Where |
|---|---|
| FastAPI app factory + routers | `api/app.py` |
| JWT auth: signup / login / refresh / me, argon2 | `service/auth.py` (295 LOC) |
| Role authorization dependency | `api/dependencies.py:require_role` |
| Upload → blob + metadata row | `service/document_service.py` |
| Disk blob store, streaming, sha256 in one pass | `storage/blob/disk.py` |
| Ingest pipeline: load → split → embed → index | `ingest/pipeline.py` |
| Ports: `DocumentStore`, `DocumentMetaStore`, `UserStore` | `storage/store/` |
| Pydantic-settings config | `config/config.py` |

### Parked in `.bak/` — revive, don't rewrite

~815 LOC of **structure-aware** parsing/chunking that is strictly better than the
flat `RecursiveCharacterTextSplitter` currently wired in:

- `parser/markdown.py` (330 LOC) — real markdown parser producing `ParsedSection`
- `chunker/` — `Splitter` ABC with a pluggable `SizeFn` (char count by default,
  swap in a token counter without touching chunker logic), plus
  `code_splitter`, `structured_splitter`, `text_splitter` dispatched by
  `SectionKind`
- `embedder/`

This is most of Phase 3's chunking work, already designed. It needs reviving
against the current tree, not reinventing.

### Blocking bugs

1. **`migrations/env.py:9`** imports `storage.sql.database`; the module is
   `storage.sql.db`. **Alembic cannot run at all.**
2. **`users` has no migration.** ORM model exists; the initial migration only
   creates `documents_metadata`. Signup fails on a fresh DB.
3. **Embeddings are fake** — `ingest/embeddings.py` returns
   `DeterministicFakeEmbedding`. Nothing indexed so far is semantically
   meaningful.
4. **`tests/` is empty**, on an auth system.
5. **`AGENTS.md` is stale** — documents `db/`, `parser/`, `document/` packages
   that no longer exist and a `DocumentParser` ABC replaced by langchain loaders.

### Missing

No retrieval/search/chat/LLM. No workspaces. No hybrid search. No connectors. No
parsers past `text/*`. No conversations, API keys, audit log, background jobs,
MCP, CLI, web UI, SDK, Docker.

---

## 3. Storage decision (locked) — and the one consequence

**SQLite + LanceDB, chunks in LanceDB.** This is a sound call and I verified it
against the installed `lancedb 0.34.0` rather than trusting docs. Everything
needed works:

| Capability | Verified |
|---|---|
| Native FTS index, **no tantivy dependency** | ✅ `create_fts_index(use_tantivy=False)` |
| Pure keyword search | ✅ `query_type="fts"` |
| **Hybrid** dense+sparse with RRF | ✅ `.vector(v).text(q)` |
| Hybrid **+ `where` filter** (workspace isolation) | ✅ |
| Explicit `RRFReranker` | ✅ |
| **Async** client with full hybrid + filter parity | ✅ `connect_async()` |
| FTS sees rows added after index build | ✅ no reindex needed for correctness |

So: you were right that LanceDB gives you hybrid search. One correction to the
plan that follows from it, though —

### The langchain `VectorStore` port has to go

Atlas currently reaches LanceDB through langchain's wrapper
(`storage/vector/lancedb.py` re-exports it; `storage/store/vector.py` aliases
langchain's `VectorStore` as the port). **Hybrid search is not reachable through
that path.** Two independent reasons, both verified:

1. langchain's wrapper embeds the query itself and passes a *single* value to
   `tbl.search()`. Hybrid needs **both** the vector and the raw text. Through the
   wrapper it fails with `ValueError: No embedding function for vector` unless
   you register a LanceDB-native embedding function on the table — which Atlas
   doesn't do and shouldn't have to.
2. The wrapper's hybrid branch is **outright broken** in langchain-community
   0.4.2: `TypeError: _query() got multiple values for keyword argument 'name'`.

`fts=True` (sparse-only) does work through the wrapper, but sparse-only is not
hybrid.

This is not a reason to change storage — LanceDB is fine. It means the **port
must be Atlas's own**, over the native async `lancedb` client. That is also more
faithful to the existing design: `storage/store/vector.py`'s own docstring says
the goal is "to keep langchain imports out of the rest of the codebase", and it
then re-exports a langchain class as the port. Replacing it fixes that.

```python
# storage/store/chunk_index.py  — replaces storage/store/vector.py
class ChunkIndex(ABC):
    async def add(self, chunks: Sequence[Chunk]) -> None: ...
    async def search(
        self, *, workspace_id: str, query_text: str,
        query_vector: Sequence[float], k: int,
        mode: Literal["hybrid", "vector", "fts"] = "hybrid",
        filters: ChunkFilters | None = None,
    ) -> list[ScoredChunk]: ...
    async def siblings(self, document_id: str, section_id: str) -> list[Chunk]: ...
    async def delete_document(self, document_id: str) -> None: ...
```

langchain stays for **loaders and embeddings adapters only** — the places it
earns its keep.

### Decision B — model provider layer

Define Atlas's own `ModelProvider` Protocol (`generate` / `embed` / `rerank` /
`describe_image` + `capabilities` + `health_check`), with langchain adapters
underneath for provider coverage. The reference's value is the *contract*;
`rerank` and `describe_image` have no langchain equivalent anyway.

---

## 4. Target architecture

```
service/
  api/          FastAPI: routes, deps, middleware (auth, rate-limit, audit)
  service/      application services (orchestration, transactions)
  rag/          ← NEW. the product
    engine.py profiles.py retriever.py fusion.py intent.py expansion.py
    parent_doc.py reranker.py context_window.py generator.py
    grounding.py confidence.py cache.py
  ingest/       loaders, chunkers, pipeline, job worker
    chunkers/   ← revived from .bak
  parsers/      ← NEW (+ revived .bak/parser)
  connectors/   ← NEW
  models/       domain dataclasses + provider protocol + adapters
  plugins/      ← NEW. entry-point registry
  storage/
    store/      ports (ABCs) — incl. NEW ChunkIndex, replacing vector.py
    sql/        SQLite adapters + ORM
    lance/      ← NEW. native async LanceDB ChunkIndex adapter
    blob/       disk (+ later S3)
  security/     ← NEW. PII redaction, audit, alerts
  cli/          ← NEW. Typer
  mcp/          ← NEW. FastMCP
  workers/      ← NEW. ingest + connector sync
  tests/
web/            ← NEW. React + Vite
```

---

## 5. Data model

### SQLite (SQLAlchemy async + Alembic)

```
users                 (exists — needs its migration)
workspaces            id, name, slug, mode(personal|team), settings_json
workspace_members     workspace_id, user_id, role(owner|admin|member|viewer)

documents_metadata    (exists) + workspace_id, source_type, source_id,
                      connector_id, version, deleted_at, error_message
document_versions     document_id, version, content_hash, created_at
collections / collection_documents
tags / document_tags
connectors            id, workspace_id, type, config_json(encrypted),
                      status, last_sync_at, cursor
jobs                  id, workspace_id, type, payload_json, status, attempts,
                      error, scheduled_at, started_at, finished_at
conversations         id, workspace_id, user_id, title, share_token
messages              id, conversation_id, role, content, sources_json,
                      confidence, created_at
api_keys              id, workspace_id, name, key_hash, prefix, scopes[],
                      allowed_ips[], expires_at, revoked_at, last_used_at
query_logs / audit_logs / plugins
```

### LanceDB — the `chunks` table

One table, **explicit pyarrow schema** (never infer from first insert — the
vector dim and nullability must be stable):

```
id              string   (pk)
document_id     string
workspace_id    string   ← every search filters on this
chunk_index     int32
text            string   ← FTS index lives here
chunk_type      string   (semantic|code|table|slide|api)
heading_path    list<string>
section_id      string   ← parent-doc expansion key
language        string
page            int32
token_count     int32
content_hash    string
vector          fixed_size_list<float32, N>
```

Indexes: FTS on `text` (native, `use_tantivy=False`); vector index (IVF_PQ or
HNSW) once row count justifies it — brute force is fine early.

**Invariants:**
- Every `search()` passes `where("workspace_id = ...")` with **`prefilter=True`**.
  Postfilter (langchain's default) silently truncates result sets below `k`.
- Re-index = `delete_document()` then `add()`, never blind append.
- `optimize()` periodically in the worker — not needed for correctness, only
  for compaction/performance.

**Note:** SQLite holds no chunk rows. Citation rendering, parent-doc expansion,
and re-embedding all read from LanceDB. That is fine — but it means LanceDB is
now load-bearing for correctness, not just recall, so it must be in the backup
story (Phase 7) from the start.

---

## 6. Phased roadmap

Phases 0–3 are the ones that matter. After Phase 3 Atlas is a real product.

### Phase 0 — Repair the foundation *(small, blocks everything)*

- Fix `migrations/env.py` import → `from storage.sql.db import Base`
- Migration for `users`
- Real embeddings behind config; keep the fake as explicit
  `EMBEDDING_PROVIDER=fake` test mode
- Rewrite `AGENTS.md` to match the real tree
- `pytest-asyncio` + `httpx`; first tests: auth round-trip, upload→ingest
- `.env.example`, CI (ruff, mypy strict, pytest)

**Done when:** `alembic upgrade head` succeeds on an empty DB, signup works,
tests pass.

### Phase 1 — `ChunkIndex` + workspaces

- Replace `storage/store/vector.py` with the `ChunkIndex` port (§3); implement
  `storage/lance/chunk_index.py` on native async lancedb
- Drop `langchain_community.vectorstores.LanceDB` from `api/dependencies.py`
- Explicit pyarrow schema + FTS index creation on first open
- `workspaces` + `workspace_members`; `workspace_id` on every document and chunk;
  personal mode = one implicit workspace
- Rewrite `IngestionPipeline` to emit `Chunk` domain objects → `ChunkIndex.add`
- Content-hash dedup; `document_versions` bump on change

**Done when:** ingesting produces LanceDB chunk rows with vector + FTS, scoped to
a workspace, and a raw `ChunkIndex.search(mode="hybrid")` returns sane results.

### Phase 2 — Retrieval + generation *(where Atlas becomes a product)*

**2a search** — `rag/retriever.py` over `ChunkIndex` hybrid; `rag/profiles.py`
(`fast`/`balanced`/`precise`/`custom`); `GET /search`.
LanceDB does RRF internally; keep `rag/fusion.py` for merging *across* expanded
queries (multi-query/HyDE), which LanceDB does not do for you.

**2b answer** — `ModelProvider` protocol + OpenAI/Anthropic/Ollama adapters;
`rag/generator.py` (prompt assembly, citations, streaming);
`rag/context_window.py` (tiktoken budget fitting); `rag/confidence.py` +
`rag/grounding.py`; `POST /chat` + `POST /chat/stream` (SSE).

**2c quality** (profile-gated, this order): parent-doc expansion (cheapest big
win — `section_id` scan) → LLM rerank → intent classify + `chunk_type` boost →
multi-query, then HyDE → decomposition → query cache → cross-encoder.

**2d conversations** — `conversations`/`messages`, history trimming, share links.

**Done when:** `POST /chat` returns a grounded, cited answer over your documents,
and `profile=precise` measurably changes the result.

### Phase 3 — Parsers, chunking, background ingestion

- **Revive `.bak/parser` + `.bak/chunker`** against the current tree; wire
  `SizeFn` to a real tokenizer
- `Parser` Protocol; add pdf (`pypdf` + OCR fallback), docx, xlsx/csv,
  html, code (tree-sitter), jupyter, email, pptx, json/yaml/toml
- Parser fallback chains (PDF text → OCR)
- Contextual retrieval: LLM-generated document-context prefix per chunk before
  embedding
- `jobs` table + `workers/ingest_worker.py`; ingest becomes 202 + poll/SSE

### Phase 4 — Connectors

`Connector` Protocol (`discover`/`fetch`/`watch`/`auth`/`health_check`), in
effort-to-value order: local files (watchdog) → web crawler → GitHub → Notion →
S3/GCS → Google Drive → Confluence → Swagger → web search (Tavily, query-time).
Plus encrypted credential storage, incremental sync cursors, scheduled sync.

### Phase 5 — Team mode / security

API keys (`atl_live_`, SHA-256 hashed, scopes, IP allowlist, expiry) · rate
limiting · PII redaction before cloud LLM calls · audit log · security alerts ·
OAuth SSO · admin API · a test asserting cross-workspace leakage is impossible.

### Phase 6 — Interfaces

CLI (Typer): `init`/`index`/`ask`/`search`/`doctor`/`workspace`/`connector`/
`backup`/`restore`/`export`/`import`/`serve` · **MCP server (FastMCP)** —
`search_documents`, `ask_question`, `list_documents`, `get_document` · Python
SDK · React web UI (the reference's `web/` maps 1:1 to this API surface).

### Phase 7 — Extensibility + ops

Plugin runtime via entry points (`atlas.parsers`/`.connectors`/`.models`) with
version constraints, permissions, health checks · middleware hooks · event bus ·
**eval harness** (hit@3/5, MRR, nDCG@5) · telemetry + degraded-mode `/health` ·
**backup/restore covering SQLite *and* LanceDB** · Docker · docs site.

---

## 7. Fastest path to something you'd use daily

**0 → 1 → 2a → 2b → 3 (markdown/PDF/code only) → 6 (MCP only)**

Real embeddings, hybrid search, cited answers, your formats, plugged into Claude
Code. Connectors, team mode, web UI, plugin runtime are breadth to add against a
working core.

Build the **eval harness early** if you intend to tune 2c — HyDE, reranking and
multi-query cannot be tuned by eyeballing.

---

## 8. Open decisions

1. ~~Storage topology~~ — **locked: SQLite + LanceDB, chunks in LanceDB.**
2. **Which embedding + LLM provider first?** Blocks Phase 0. Ollama (offline,
   free, slower) vs OpenAI/Anthropic (fast, costs, needs a key). Determines the
   vector dim baked into the LanceDB schema — changing it later means a full
   re-index.
3. **Personal mode** — keep the reference's zero-auth localhost mode, or always
   authenticate? Auth is already built, so "always on" is cheaper.
4. **Parity scope** — 21 plugins is a lot of surface for a solo project.
5. **Web UI** — build it, or ship CLI + MCP + API only? MCP may make it optional.
