# RenoPreview Agent Rules & Ownership Contract

## 1. Spend Rules & Credit Protection
- **Bring Your Own Key (BYOK)**: Customers connect their own Magic Hour API key (`POST /api/connections/magic-hour`) and pay Magic Hour directly for media credits.
- **No Personal Key Fallback**: Never configure or fall back to a personal or shared developer `MAGIC_HOUR_API_KEY`. An absent or expired user key must immediately stop new live work (`not_connected` / `waiting_for_key`).
- **Immutable Quote & Explicit Consent**: Every paid generation (`image` or `video`) requires an immutable `BriefRevision`, a fresh `Quote` bound to the exact output request hash, and explicit user confirmation with an `idempotency_key`.
- **Video Workflow Pauses for Image Review**: A video request starts the mandatory flow (`connect key -> add photo -> review brief -> confirm image quote -> generate image -> approve exact image -> confirm clip quote -> generate and review clip -> assemble rooms and export`). Never spend video credits before the user accepts the exact generated still image.
- **No Silent Retries or Model Switching**: Never put a retry decorator around paid creation calls (`POST /v1/ai-image-editor`, `POST /v1/image-to-video`). If transport fails, returns 5xx, or returns a malformed response without a string `id`, transition to `submission_unknown` and require reconciliation. Never silently switch models or resolutions.
- **Retain Completed Stages**: If a later clip stage is blocked by insufficient credits or credential expiry, preserve the completed still image and its human acceptance record. Resume only the pending clip stage after balance refresh and a fresh clip quote.

## 2. Offline Defaults & Mock Mode
- `GATEWAY_MODE=mock` is the default for local development and automated tests.
- All unit, integration, contract, and Playwright end-to-end tests must run against `mock` mode or fake transport without spending external credits.
- Any mock test token (e.g., `mhk_mock_*`, `mock_*`, `test_*`) is strictly rejected by `MagicHourGateway` so test credentials can never enter the live adapter.

## 3. Source & Quote Requirements
- Every generation must record:
  - `source_asset_id` (verified owned room photo or accepted concept image)
  - `brief_revision_id` (immutable snapshot; editing a room's brief later never mutates an in-flight or completed generation)
  - `compiler_version` (`reno-brief-v1`)
  - `catalog_version` (`mh-catalog-2026-10-03-v1`)
  - `quote_id` (unexpired, matching `spec_hash`)
  - `provider_id` (persisted immediately upon creation response before polling)

## 4. No Secret Logging & Privacy Controls
- Never log raw Magic Hour API keys, `Authorization` headers, cookies, signed upload/download URLs, or internal storage paths in request logs, exception traces, job events, or error responses.
- Never store raw API keys in Postgres or browser `localStorage`/`sessionStorage`. Store only a masked suffix, key fingerprint, and HMAC account fingerprint in Postgres; store the AES-GCM encrypted key in Redis with a strict TTL.
- Strip EXIF GPS location, camera metadata, and embedded thumbnails from all uploaded room photos before private storage.
- Enforce session owner checks on every project, room, asset, brief, quote, generation, review, presentation, and export query. Return `404` for another owner's object to avoid confirming existence.

## 5. File Ownership
- **Integrator**: `README.md`, `AGENTS.md`, `.env.example`, `docs/*`, `config/model-catalog.json`, `backend/migrations/*`, `backend/app/domain/*`, `frontend/src/api/*`, lockfiles.
- **Backend API & Services**: `backend/app/main.py`, `backend/app/settings.py`, `backend/app/dependencies.py`, `backend/app/api/*`, `backend/app/services/*`, `backend/app/repositories/*`.
- **Gateways & Workers**: `backend/app/gateways/*`, `backend/app/workers/*`.
- **Frontend Features**: `frontend/src/app/*`, `frontend/src/features/*`, `frontend/src/styles/tokens.css`, `frontend/tests/flows.spec.ts`.
