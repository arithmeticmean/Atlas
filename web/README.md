# Atlas Web

React + Vite UI for the Atlas RAG service (JavaScript, no TypeScript). Talks to
the FastAPI backend under `/api/v1`.

## Develop (hot reload)

Run the backend and the Vite dev server side by side:

```bash
# terminal 1: API on :8000, with a separate development data folder
cd .. && ATLAS_DATA_PATH=~/.atlas-dev uv run atlas

# terminal 2: UI on :5173, proxies /api to :8000
npm install
npm run dev
```

Open http://localhost:5173. On first run, the setup token is printed in
terminal 1.

## Build

```bash
npm run build          # emits ../src/atlas/static
```

FastAPI then serves the UI and the API together on http://127.0.0.1:8000.
Building the Python package (`uv build`, or the first `uv sync`) runs this
through `scripts/hatch_build.py`.

## Structure

- `src/lib/`: the API client, session, routing and shared hooks.
- `src/ui/`: the design system (buttons, fields, dialogs, toasts, the map art).
- `src/pages/`: one file per screen. `Shell.jsx` is the signed-in layout.
- `src/styles.css`: colors for both themes, in one place.

The access token stays in memory and the refresh token is an httpOnly cookie,
so nothing that grants access is readable from browser storage.
