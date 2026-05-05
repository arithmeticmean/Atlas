# Atlas Web

React + Vite UI for the Atlas RAG service (JavaScript, no TypeScript). Talks to
the FastAPI backend under `/api`.

## Develop (hot reload)

Run the backend and the Vite dev server side by side:

```bash
# terminal 1 — backend on :8000
cd ../service && uv run uvicorn api.app:app --reload

# terminal 2 — UI on :5173, proxies /api -> :8000
npm install
npm run dev
```

Open http://localhost:5173.

## Build (served by FastAPI, no nginx)

```bash
npm run build          # emits ./dist
```

The backend serves `dist/` automatically: `settings.frontend_dir` defaults to
`../web/dist` (resolved from the service root). So in production just run the
backend and it serves both the UI and the API on one origin:

```bash
cd ../service && uv run uvicorn api.app:app
# open http://localhost:8000
```

## Structure

- `src/lib/api.js` — fetch wrapper for the `/api` endpoints.
- `src/lib/sse.js` — Server-Sent Events reader for the streaming `/api/answer`.
- `src/components/` — pages: Chat (streamed answers), Search (raw retrieval),
  Documents (upload + status), Connectors (CRUD + health + last-sync + sync
  now), Health (readiness + admin diagnostics).
- `src/App.jsx` — sidebar nav + readiness banner.

Navigation is in-app state (no router), so there are no deep-link routes to
worry about; the FastAPI SPA fallback is still in place if you add one later.
