# RenoPreview Data, Ownership, and API Contracts

## 1. Durable Entities & Invariants
- **Session (`sessions`)**: Stores `id_hash` (HMAC-SHA256 of cookie token), `csrf_token`, `created_at`, `expires_at`. Raw cookie token is never stored in Postgres.
- **CredentialReference (`credential_references`)**: Stores `vault_ref`, `key_fingerprint`, `masked_suffix`, `provider_account_fingerprint`, `tier`, `balance`, `balance_checked_at`, `expires_at`. Raw API key is encrypted with AES-GCM in Redis under `vault_ref`.
- **Project (`projects`)**: Scoped by `owner_id_hash`. Every lookup filters by `owner_id_hash` and `deleted_at IS NULL`, returning `404` for unauthorized or missing IDs.
- **Room (`rooms`)**: Belongs to one owned project; capped at 5 rooms per project in launch mode.
- **Asset (`assets`)**: Private storage key generated server-side (`secrets.token_hex`). Stripped of EXIF GPS/camera metadata. Served only via short-lived HMAC-signed URLs after owner verification.
- **BriefRevision (`brief_revisions`)**: Immutable after submission; retains `parent_revision_id`, `raw_text`, structured `RenovationBrief` JSON, `compiled_prompt`, `source_hash`, and `compiler_version`.
- **Quote (`quotes`)**: Bound to `brief_revision_id`, `source_asset_id`, `model`, `resolution`, and `spec_hash`. Expires after 5 minutes.
- **Generation (`generations`)**: Enforces `UNIQUE(owner_id_hash, idempotency_key)`. Tracks `state` separately from `provider_state`.
- **ProviderAttempt (`provider_attempts`)**: Records each submission attempt and `provider_id`.
- **Review (`reviews`)**: Records human `accept`, `revise`, or `reject` decision and preservation checklist against the exact `asset_id`.
- **CreditEvent (`credit_ledger`)**: Enforces `UNIQUE(attempt_id, event_type)` so observed provider charges are never double-counted.
- **Presentation (`presentations`) & Export (`exports`)**: Immutable ordered clip manifest (`presentation-v1`) rendered locally via FFmpeg without calling Magic Hour.

## 2. Application Endpoints
- `POST /api/session` — Initialize or refresh `HttpOnly` session cookie and CSRF token
- `POST /api/connections/magic-hour` — Validate key via `GET /v1/account`, encrypt into Redis, return masked status, tier, and credits
- `GET /api/connections/magic-hour` — Current connection state and last checked timestamp
- `POST /api/connections/magic-hour/refresh` — Fetch fresh balance from Magic Hour
- `DELETE /api/connections/magic-hour` — Delete vault credential and stop future live submissions
- `POST /api/projects` / `GET /api/projects` / `GET /api/projects/{id}` / `DELETE /api/projects/{id}`
- `POST /api/projects/{id}/rooms` / `PATCH /api/rooms/{id}`
- `POST /api/rooms/{id}/assets` — Streamed multipart upload, EXIF orientation, metadata strip, private storage
- `POST /api/rooms/{id}/briefs` — Compile immutable structured `BriefRevision` and check contradictions
- `POST /api/quotes` — Compute credit estimate and workflow cost bound to exact brief and source asset
- `POST /api/generations` — Idempotent transactional admission + outbox insert
- `GET /api/generations/{id}` — Recovery authority job snapshot
- `GET /api/generations/{id}/events` — SSE job progress stream with `Last-Event-ID` support
- `POST /api/assets/{id}/reviews` — Record human review (`accept`, `revise`, `reject`)
- `POST /api/generations/{id}/resume` — Resume blocked or reconciled job with fresh quote when required
- `POST /api/generations/{id}/stop` — Halt future app work for job
- `POST /api/projects/{id}/presentations` — Create multi-room presentation assembly job
- `GET /api/exports/{id}` — Export status and signed download links for MP4, room media, and Markdown brief
