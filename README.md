# RenoPreview — Renovation Concept Visualization

RenoPreview is a web application where customers connect their own Magic Hour API key, upload a room photograph, author and review a structured renovation brief with explicit feature preservation controls, confirm a credit quote, generate and review a renovated concept image, approve the exact image, confirm a separate video clip quote, generate and review a room video clip, and assemble an ordered room-by-room presentation with a contractor handoff brief.

> **Important**: RenoPreview produces visual concepts, not validated 3D reconstructions, continuous floor-plan walkthroughs, or construction drawings. Every paid provider stage requires an immutable brief revision, fresh quote, and explicit customer confirmation.

## Architecture & Defaults
- **Frontend**: React 18 + TypeScript + Vite (`frontend/`), routing `/api` through a same-origin reverse proxy.
- **Backend API**: Python FastAPI (`backend/app/main.py`) with `HttpOnly` SameSite session cookies, CSRF validation, owner isolation on every query, and safe error envelopes.
- **Database**: PostgreSQL 16 (`backend/migrations/001_initial_schema.sql`) for durable projects, rooms, assets, brief revisions, quotes, generations, provider attempts, reviews, credit ledger, presentations, exports, job events, and transactional outbox.
- **Vault & Coordination**: Redis (`backend/app/services/credential_vault.py`) for AES-GCM encrypted short-lived credentials, rate limiting, and per-account concurrency locks.
- **Worker**: Separate long-running worker (`backend/app/workers/runner.py`) for outbox dispatch, provider submission, backoff polling, bounded downloads, and local FFmpeg assembly.
- **Default Gateway**: `GATEWAY_MODE=mock` is the default offline-safe mode. No personal Magic Hour API key fallback exists.

## Exact Run, Migration, Test, and Build Commands

### 1. Install Dependencies
```bash
# Backend (from repository root)
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt

# Frontend
npm --prefix frontend ci
```

### 2. Start Local Services & Apply Migrations
```bash
# Ensure PostgreSQL 16 and Redis are running locally (or via docker compose -f infra/compose.yaml up -d postgres redis)
export PATH="/opt/homebrew/opt/postgresql@16/bin:/opt/homebrew/opt/redis/bin:/opt/homebrew/bin:$PATH"
createdb renopreview 2>/dev/null || true

# Apply SQL migrations to the database
PYTHONPATH=backend backend/.venv/bin/python -c "from app.dependencies import apply_migrations; print(apply_migrations())"
```

### 3. Run API, Worker, and Frontend Dev Server
```bash
# Terminal 1 — FastAPI Backend (Mock Mode by default)
PYTHONPATH=backend backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — Durable Worker
PYTHONPATH=backend backend/.venv/bin/python -m app.workers.runner

# Terminal 3 — Vite Frontend (proxies /api to http://127.0.0.1:8000)
npm --prefix frontend run dev
```

### 4. Health & Readiness Endpoints
- Process Liveness: `curl -fsS http://127.0.0.1:8000/health`
- Dependency Readiness: `curl -fsS http://127.0.0.1:8000/ready`

### 5. Run Tests & Frontend Build
```bash
# Backend Unit, Integration, and Provider Contract Tests
PYTHONPATH=backend backend/.venv/bin/pytest backend/tests -v

# Frontend Typecheck, Lint, and Production Build
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run build

# End-to-End Playwright Suite
npm --prefix frontend run test:e2e
```
