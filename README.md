# Atlas

Chat with your documents on your own server.

Atlas is a self-hosted knowledge assistant. Upload files, invite your team, and
talk to it like a normal AI assistant. When your documents help, answers cite
the exact passages they came from. When they don't, Atlas answers from general
knowledge, with no citation.

One process serves the web app and the API. Your files, search index and chats
stay in one folder on your machine.

## Features

- **Chat with sources:** streaming answers, clickable citations, stop,
  regenerate, feedback, pinned and archived chats, Markdown export.
- **Any model:** Ollama, OpenAI, Anthropic, Google, or any OpenAI-compatible
  API such as Kimi, LM Studio, vLLM or OpenRouter.
- **Documents:** drag-and-drop upload, live indexing status, tags, filters and
  a preview of what Atlas read.
- **Teams:** separate projects, member roles and invite links. Chats are
  private to the person who started them.
- **Connectors:** import web pages and Google Drive files.
- **Safe defaults:** API keys are encrypted, and credential files such as
  `.env` and `.pem` are never indexed.

## Quick start

You need [uv](https://docs.astral.sh/uv/) and [Node.js](https://nodejs.org/).
Node is only used to build the web app.

```bash
git clone <your-repo-url> atlas
cd atlas
uv sync
uv run atlas
```

Then:

1. Open <http://127.0.0.1:8000>.
2. Copy the **setup token** printed in the terminal and create the owner
   account. A new token is printed each time Atlas starts until setup is done.
3. Connect a **chat model** and an **embedding model**.
4. Create a project, add documents and start chatting.

## Choosing models

Atlas uses two models, and they can come from different providers:

- The **chat model** writes the answers.
- The **embedding model** makes your documents searchable by meaning.

| Provider | What to enter | Good for |
|---|---|---|
| Ollama | Address, usually `http://localhost:11434` | Private, free, local |
| OpenAI, Google | API key | Chat and embeddings |
| Anthropic | API key | Chat only |
| OpenAI-compatible | Server address, API key if needed | Kimi, LM Studio, vLLM, OpenRouter |

For a fully local setup, pull the models before connecting them:

```bash
ollama pull nomic-embed-text
ollama pull llama3.1
```

To use Kimi, choose **OpenAI-compatible**, enter `https://api.moonshot.ai/v1`
and your API key, then pick a model such as `kimi-k2.6`.

Changing the embedding model re-indexes every document. Uploads and answers
pause until that finishes.

### Speed

- **Indexing** time is mostly the embedding model. On a laptop CPU with
  `nomic-embed-text`, expect roughly 0.3 seconds per passage, or about 4 to 5
  minutes for a 330-page PDF. A GPU or a hosted embedding model is much faster.
- **Chat** speed depends on the chat model. **Deep thinking** is off by default
  for Kimi K2.6 because it can add a minute or more. Turn it on under
  **Settings → Answers & documents**.

## Supported files

| Type | Extensions |
|---|---|
| Documents | `.pdf` `.html` `.htm` `.md` `.markdown` `.rst` `.tex` `.txt` `.log` |
| Data and config | `.csv` `.tsv` `.json` `.jsonl` `.xml` `.yaml` `.yml` `.toml` `.ini` `.cfg` `.conf` `.sql` |
| Code | `.py` `.js` `.jsx` `.mjs` `.cjs` `.ts` `.tsx` `.go` `.rs` `.c` `.h` `.cc` `.cpp` `.cxx` `.hh` `.hpp` `.java` `.kt` `.scala` `.cs` `.php` `.rb` `.swift` `.lua` `.r` `.hs` `.ex` `.exs` `.pl` `.sh` `.bash` `.ps1` `.css` `.proto` `.sol` `.cob` |

Atlas checks each file's real content, so a renamed file can't get past it.
Scanned PDFs have no text to read, and `.docx` isn't supported yet.

## Configuration

Atlas needs only four environment variables, all optional. Everything else is
changed in **Settings** and stored in the database.

| Variable | Default | Purpose |
|---|---|---|
| `ATLAS_DATA_PATH` | `~/.atlas` | Where all data lives |
| `ATLAS_HOST` | `127.0.0.1` | Address to listen on |
| `ATLAS_PORT` | `8000` | Port to listen on |
| `ATLAS_MASTER_KEY` | Generated file | Encrypts API keys and signs sessions |

```bash
ATLAS_DATA_PATH=/srv/atlas ATLAS_HOST=0.0.0.0 ATLAS_PORT=9000 uv run atlas
```

### Your data

```text
~/.atlas/
  db/atlas.db    users, projects, chats, settings
  vector_db/     the search index
  documents/     your uploaded files
  master.key     encrypts your API keys
```

To back up, stop Atlas and copy the whole folder. Keep `master.key` with it:
without that key, saved API keys must be entered again and everyone must sign
in again. Database upgrades run automatically at startup.

## Sharing it with a team

By default, only your own computer can reach Atlas. To share it on a trusted
network, set `ATLAS_HOST=0.0.0.0`.

**Don't expose Atlas directly to the internet yet.** It has no built-in HTTPS
or login rate limiting. Put it behind a VPN, or behind a reverse proxy with
HTTPS and access control. If you use a proxy, turn off response buffering for
`/api/` so chat answers keep streaming.

## Known limitations

- There is no standalone search page. Search happens through chat.
- Forgotten passwords need an admin's reset link, and the owner has no recovery
  path yet.
- Invite links can't be listed or revoked before they expire.
- A disabled user's current session can keep working until its access token
  expires.
- Connector credentials are stored in the database without encryption, and URL
  connectors can reach internal addresses. Only give connector access to people
  you trust.
- Connector syncs run while you wait rather than in the background.

## Development

```bash
uv sync                  # install Atlas and the dev tools

# Terminal 1: the API, with a separate data folder
ATLAS_DATA_PATH=~/.atlas-dev uv run atlas

# Terminal 2: the web app with hot reload, at http://localhost:5173
cd web && npm install && npm run dev
```

API docs are served at <http://127.0.0.1:8000/api/docs>.

After changing the web app, run `npm run build` in `web/` so the server on port
8000 serves the new version.

### Checks

```bash
uv run pytest                # everything, in about 20 seconds
uv run pytest -m "not e2e"   # skip the real-server tests
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

Tests use temporary folders and fake model servers. They never touch your data,
Ollama or a paid API. `tests/test_e2e.py` starts a real Atlas server and drives
it over HTTP.

### Build a package

```bash
uv build
uv tool install --force ./dist/atlas-0.1.0-py3-none-any.whl
atlas
```

The build compiles the web app into the wheel, so installing the wheel doesn't
need Node.

### Project layout

```text
src/atlas/
  main.py        app and server entry point
  container.py   wires everything together
  config/        environment settings and encryption
  controllers/   HTTP: request in, one service call, response out
  services/      business rules: auth, projects, documents, chat, settings
  repository/    database and file storage
  models/        database entities
  core/          the AI engine: parsing, providers, vector store, chat
  migrations/    database migrations
web/             React app
tests/           focused tests and the backend e2e
scripts/         build hook that compiles the web app
```
