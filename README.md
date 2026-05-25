# Enterprise Knowledge Assistant

## Local Setup

The repository now includes a Next.js frontend in `frontend/`, Dockerfiles in `docker/`, and a Compose stack for `frontend`, `backend`, `postgres` with `pgvector`, and `redis`.

1. Copy `.env.example` to `.env` and adjust values if your backend module path or ports differ.
   For Docker Compose, keep `BACKEND_INTERNAL_URL=http://backend:8000`. Use `http://localhost:8000` only when the frontend runs outside Docker.
2. Start the stack with `docker compose up --build`.
3. Open `http://localhost:3000` for the frontend and `http://localhost:8000/api/v1/health` for the backend health endpoint.
4. Optional backend-only checks: run `/Users/neecat/projects/rag-project/backend/.venv/bin/pytest tests/backend -q`.

Notes:

- The frontend targets `NEXT_PUBLIC_API_BASE_URL`, defaulting to `/api/v1`, and Next.js rewrites that path to `BACKEND_INTERNAL_URL`.
- The backend reads `DATABASE_URL` and `REDIS_URL` from Compose, and also supports `APP_DATABASE_URL` for direct local backend runs.
- `NEXT_PUBLIC_ENABLE_DEMO_DATA=false` is the default for integrated local runs. Set it to `true` only if you explicitly want frontend demo fallbacks while the backend is unavailable.
- The backend container defaults to `uvicorn app.main:app`. If your FastAPI entrypoint lives elsewhere, change `BACKEND_APP_MODULE` in `.env`.
- The backend allows local frontend origins through `APP_CORS_ORIGINS`, and the same-origin rewrite path means browser calls should not need cross-origin configuration in the normal Docker flow.
- `npm run build` is currently the reliable frontend verification step. `npm run lint` still triggers Next.js interactive ESLint setup because no ESLint config has been committed yet.
- Current backend/frontend-aligned placeholder routes:
  - `GET /api/v1/health`
  - `GET,POST /api/v1/sources`
  - `POST /api/v1/sources/{source_id}/upload`
  - `POST /api/v1/sources/{source_id}/sync`
  - `GET /api/v1/documents`
  - `POST /api/v1/documents/upload`
  - `GET /api/v1/documents/{document_id}/status`
  - `GET,POST /api/v1/conversations`
  - `GET /api/v1/conversations/{conversation_id}`
  - `POST /api/v1/conversations/{conversation_id}/messages`
  - `POST /api/v1/chat`
