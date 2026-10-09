# RenoPreview Implementation Progress

## Phase 1: Repository, contracts, storage and ownership — COMPLETE
- **Implemented Tasks**:
  - Initialized `frontend/` (React 18, TypeScript, Vite, Playwright) and `backend/` (FastAPI, Pydantic v2, psycopg2, Redis, Pillow, httpx) with locked dependencies (`package-lock.json` and `backend/requirements.txt`).
  - Added `backend/app/settings.py`, `.env.example`, `/health` and `/ready` endpoints, and default `GATEWAY_MODE=mock`.
  - Created `backend/migrations/001_initial_schema.sql` for sessions, credential_references, projects, rooms, assets, brief_revisions, quotes, generations, provider_attempts, reviews, credit_ledger, presentations, exports, job_events, and outbox.
  - Implemented hashed `HttpOnly` session cookie creation (`POST /api/session`), CSRF validation, and owner isolation dependencies in `backend/app/dependencies.py`.
  - Defined safe error envelopes (`backend/app/domain/errors.py`), explicit job states (`backend/app/domain/states.py`), gateway interface (`backend/app/gateways/base.py`), and shared Pydantic schemas (`backend/app/domain/schemas.py`).
  - Synchronized frontend API types (`frontend/src/api/types.ts`) and safe error client (`frontend/src/api/client.ts`).
  - Added mock seed project support (`is_mock_seed=true`) and static UI shell (`frontend/src/app/routes.tsx`).
  - Added `README.md`, `AGENTS.md`, `docs/architecture.md`, `docs/contracts.md`, `docs/provider-reference.md`, and `docs/release-checklist.md`.
- **Checks Actually Run**:
  - `PYTHONPATH=backend backend/.venv/bin/python -c "from app.dependencies import apply_migrations; print('Applied migrations:', apply_migrations())"` -> Applied `001_initial_schema.sql`
  - `PYTHONPATH=backend backend/.venv/bin/pytest backend/tests/integration/test_phase1_foundation.py -v` -> 2 passed in 0.15s
  - `npm --prefix frontend run typecheck` -> Passed (0 errors)
  - `npm --prefix frontend run build` -> Passed (`dist/` built in 3.40s)
- **Failures**: None.
- **Remaining Work**: Phases 2 through 12.

## Phase 2: Magic Hour connection and credit refresh — COMPLETE
- **Implemented Tasks**:
  - Implemented `backend/app/services/credential_vault.py` using AES-GCM encryption (`CREDENTIAL_ENCRYPTION_KEY`, key version `v1`) with AAD binding to `owner_id_hash` and `provider_account_fingerprint`, Redis TTL storage under `vault:cred:{vault_ref}`, and Postgres metadata persistence without plaintext keys.
  - Added `backend/app/api/connection.py` (`POST /api/connections/magic-hour`, `GET /api/connections/magic-hour`, `POST /api/connections/magic-hour/refresh`, `DELETE /api/connections/magic-hour`) with strict rejection of keys in query strings or unexpected headers, pausing active jobs to `waiting_for_key` on disconnect or TTL expiry, and resuming them when a valid key is reconnected.
  - Built `frontend/src/features/connection/ConnectModal.tsx` and `frontend/src/features/connection/CreditStatus.tsx` with debounced window-focus refresh in `frontend/src/app/providers.tsx`.
- **Checks Actually Run**:
  - `PYTHONPATH=backend backend/.venv/bin/pytest backend/tests/integration/test_phase2_connection.py -v` -> 3 passed in 0.44s
  - `npm --prefix frontend run typecheck && npm --prefix frontend run build` -> Passed
- **Failures**: None.
- **Remaining Work**: Phases 3 through 12.

## Phase 3: Room photos and input processing — COMPLETE
- **Implemented Tasks**:
  - Implemented `backend/app/services/asset_service.py` with streamed byte limit checks (`MAX_UPLOAD_BYTES=15728640`), true image format decoding (`JPEG`, `PNG`, `WEBP`), decompression bomb pixel limit (`MAX_IMAGE_PIXELS=24000000`), animated image rejection, actionable HEIC/HEIF conversion guidance, EXIF orientation transpose (`ImageOps.exif_transpose`), full metadata/GPS/thumbnail stripping, alpha flattening onto neutral background, aspect-preserving resize within `2048px`, edge-variance blur advisory, SHA-256 hashing, private random storage keys, and HMAC-signed download URLs.
  - Implemented `backend/app/api/assets.py` (`POST /api/rooms/{room_id}/assets`, `GET /api/assets/{asset_id}`, `PATCH /api/assets/{asset_id}/annotations`, `GET /api/assets/{asset_id}/download`) and `backend/app/services/retention_service.py` for tombstone file cleanup.
  - Implemented `frontend/src/features/rooms/PhotoUploader.tsx` with photo upload/replacement, normalization badges, advisory banner, and pin annotations.
- **Checks Actually Run**:
  - `PYTHONPATH=backend backend/.venv/bin/pytest backend/tests/unit/test_photo_normalization.py -v` -> 3 passed
  - `npm --prefix frontend run typecheck && npm --prefix frontend run build` -> Passed
- **Failures**: Fixed `create_room` cursor fetch order in `backend/app/repositories/projects.py` and aligned `assets` JSON column names (`annotations_json`, `normalization_transform_json`) with `001_initial_schema.sql`; re-ran and passed.
- **Remaining Work**: Phases 4 through 12.

## Phase 4: Renovation brief and prompt compiler — COMPLETE
- **Implemented Tasks**:
  - Implemented `backend/app/services/compiler.py` (`extract_changes_from_text`, `detect_brief_conflicts`, `compile_image_prompt`, `compile_video_prompt`, `compute_brief_source_hash`, and `BriefService`) using `compiler_version="reno-brief-v1"`.
  - Enforced camera movement exclusion from still image prompts, preservation lock conflict detection, contradictory target finish detection, and prompt injection sanitization without altering gateway config.
  - Implemented `backend/app/api/briefs.py` (`POST /api/rooms/{room_id}/briefs`, `GET /api/rooms/{room_id}/briefs`) with immutable revision history.
  - Created `frontend/src/features/rooms/PreserveControls.tsx` and `frontend/src/features/rooms/BriefEditor.tsx`.
- **Checks Actually Run**:
  - `PYTHONPATH=backend backend/.venv/bin/pytest backend/tests/unit/test_brief_compiler.py -v` -> 4 passed (12 total backend tests passed)
  - `npm --prefix frontend run typecheck && npm --prefix frontend run build` -> Passed
- **Failures**: Fixed Python 3.9 `Optional[BriefRevisionResponse]` decorator evaluation in `backend/app/api/briefs.py` and comma-separated clause splitting in `extract_changes_from_text`; re-ran and passed.
- **Remaining Work**: Phases 5 through 12.

## Phase 5: Model capabilities, quotes and admission — COMPLETE
- **Implemented Tasks**:
  - Implemented `backend/app/services/quote_service.py` loading `config/model-catalog.json`, enforcing account tier eligibility (`free` vs `creator`/`pro`/`business`), validating resolution/duration/audio options, enforcing accepted still image review before video quotes, computing `spec_hash`, and persisting 5-minute quotes with `quote_created` ledger events.
  - Implemented `backend/app/services/admission.py` with Postgres advisory locks on `(owner_id_hash, idempotency_key)` and `account_fingerprint`, returning existing jobs on identical retries, `409 conflict` on modified payload with the same idempotency key, `409 stale_quote` on expired quotes or modified room briefs/photos, `402 insufficient_credits` when balance is below required spend, `MAX_ACTIVE_JOBS_PER_ACCOUNT=1` concurrency enforcement, and atomic insertion of `generations` + `job_events` + `credit_ledger` (`spend_authorized`) + `outbox`.
  - Implemented `backend/app/api/quotes.py` (`POST /api/quotes`, `GET /api/quotes/catalog`), `backend/app/api/generations.py` (`POST /api/generations`, `GET /api/generations/{id}`, `GET /api/generations/{id}/events`, `POST /api/generations/{id}/stop`, `POST /api/generations/{id}/resume`), and `frontend/src/features/quotes/QuoteCard.tsx`.
- **Checks Actually Run**:
  - `PYTHONPATH=backend backend/.venv/bin/pytest backend/tests/unit/test_quotes_and_idempotency.py -v` -> 3 passed (15 total backend tests passed)
  - `npm --prefix frontend run typecheck && npm --prefix frontend run build` -> Passed
- **Failures**: Added `unsupported_option`, `invalid_brief`, and `submission_unknown` to `ErrorCode` literal in `backend/app/domain/errors.py`; re-ran and passed.
- **Remaining Work**: Phases 6 through 12.

## Phase 6: Provider gateway and matching mocks — COMPLETE
- **Implemented Tasks**:
  - Recorded the reviewed Magic Hour v1 OpenAPI contract snapshot (`GET /v1/account`, `POST /v1/files/upload-urls`, `POST /v1/ai-image-editor`, `GET /v1/image-projects/{id}`, `POST /v1/image-to-video`, `GET /v1/video-projects/{id}`).
  - Verified `MagicHourGateway` (`backend/app/gateways/magic_hour.py`) and `MockGateway` (`backend/app/gateways/mock.py`) against the shared `ProviderGateway` contract, including mock token rejection in live mode, signed upload PUT without Bearer token, 402/422 error classification, and `SubmissionUnknown` without automatic retry on 5xx, timeout, or missing `id` during paid creation.
- **Checks Actually Run**:
  - `PYTHONPATH=backend backend/.venv/bin/pytest backend/tests/contract/test_magic_hour_contract.py -v` -> 2 passed (17 total backend tests passed)
- **Failures**: None.
- **Remaining Work**: Phases 7 through 12.

## Phase 7: Durable worker and recovery — COMPLETE
- **Implemented Tasks**:
  - Implemented `backend/app/workers/submit.py`, `backend/app/workers/poll.py`, `backend/app/workers/download.py`, and `backend/app/workers/runner.py`.
  - Enforced pre-submission attempt persistence (`provider_attempts.state = 'submitting'`) and `submission_started` ledger logging before paid provider calls, transitioning interrupted submissions to `submission_unknown` without automatic replay.
  - Added `GET /api/generations/{id}`, `GET /api/generations/{id}/events` (SSE with `Last-Event-ID`), `POST /api/generations/{id}/stop`, and `POST /api/generations/{id}/resume`, plus `frontend/src/features/generation/JobTimeline.tsx`.
- **Checks Actually Run**:
  - `PYTHONPATH=backend backend/.venv/bin/pytest backend/tests/integration/test_worker_recovery.py -v` -> 3 passed (20 total backend tests passed)
- **Failures**: Fixed TypeScript `String(snapshot.last_safe_error.message)` cast in `JobTimeline.tsx`.
- **Remaining Work**: Phases 8 through 12.

## Phase 8: Stored results, comparison and approval — COMPLETE
- **Implemented Tasks**:
  - Implemented bounded, host-validated output downloading and media probing (`ffprobe` for MP4 video and Pillow for still images) in `backend/app/workers/download.py`.
  - Implemented `backend/app/services/review_service.py` and `POST /api/assets/{asset_id}/reviews` supporting `accept`, `revise` (creating linked child brief revisions with next credit estimates), and `reject`.
  - Created `frontend/src/features/review/ImageCompare.tsx`, `frontend/src/features/review/ReviewChecklist.tsx`, and `frontend/src/features/review/VideoReview.tsx`.
- **Checks Actually Run**:
  - `PYTHONPATH=backend backend/.venv/bin/pytest backend/tests/integration/test_worker_recovery.py -v` -> Passed `test_phase8_download_security_and_review_decisions`
  - `npm --prefix frontend run typecheck && npm --prefix frontend run build` -> Passed
- **Failures**: None.
- **Remaining Work**: Phases 10 through 12.

## Phase 9: Approved image to video and credit recovery — COMPLETE
- **Implemented Tasks**:
  - Enforced accepted still image review gate before any video quote (`kind="video"`) or video submission.
  - Added conservative interior camera motion presets (`nearly_still`, `gentle_push`, `small_lateral`) and account-scoped upload of the accepted still image asset.
  - Verified low-credit blocking after image completion (e.g. 240 initial credits -> 190 remaining after 50-credit image -> 240-credit video quote blocked until balance refresh) while preserving the accepted still image and review.
- **Checks Actually Run**:
  - `PYTHONPATH=backend backend/.venv/bin/pytest backend/tests/integration/test_worker_recovery.py -v` -> Passed `test_phase9_video_gate_low_credit_recovery_and_video_completion` (22 total backend tests passed)
- **Failures**: None.
- **Remaining Work**: Phases 10 through 12.

## Phase 10: House presentation and exports — COMPLETE
- **Implemented Tasks**:
  - Implemented `backend/app/workers/assemble.py` normalizing accepted room clips to `1280x720@30fps libx264 yuv420p` via local FFmpeg, sanitizing label text files without shell interpolation, stitching with the `concat` demuxer, verifying with `ffprobe`, and generating the Markdown renovation handoff brief with concept limitation notice.
  - Implemented `backend/app/services/presentation_service.py` and `backend/app/api/exports.py` (`POST /api/projects/{project_id}/presentations` and `GET /api/exports/{export_id}`) with canonical `manifest_hash` idempotency.
  - Created `frontend/src/features/presentation/ClipOrderer.tsx` and `frontend/src/features/presentation/ExportPanel.tsx`.
- **Checks Actually Run**:
  - `PYTHONPATH=backend backend/.venv/bin/pytest backend/tests/integration/test_presentation_assembly.py -v` -> Passed (23 total backend tests passed)
  - `npm --prefix frontend run typecheck && npm --prefix frontend run build` -> Passed
- **Failures**: Fixed `owner.id_hash` reference in `exports.py` and `Change` schema default `source="user_control"`.
- **Remaining Work**: Phases 11 and 12.

## Phase 11: Responsive interface and integrated flow — COMPLETE
- **Implemented Tasks**:
  - Wired all room-by-room components (`RoomList`, `RoomViewer`, `BriefEditor`, `QuoteCard` for image and video, `JobTimeline`, `ImageCompare`, `ReviewChecklist`, `VideoReview`, `ClipOrderer`, `ExportPanel`) into `frontend/src/features/projects/ProjectWorkspace.tsx`.
  - Added background worker loop in `backend/app/main.py` lifespan (active when `APP_ENV != "test"`) and immediate lease release on clean `submit_job -> queued` transitions.
  - Added `backend/tests/integration/test_full_flow_acceptance.py` and `frontend/tests/flows.spec.ts` (Playwright E2E tests covering desktop + mobile viewports, full kitchen renovation + presentation assembly flow, secret isolation, and low-credit video quote recovery).
- **Checks Actually Run**:
  - `PYTHONPATH=backend backend/.venv/bin/pytest backend/tests/integration/test_full_flow_acceptance.py -v` -> 1 passed (24 total backend tests passed)
  - `npm --prefix frontend run typecheck && npm --prefix frontend run build` -> Passed
  - `npm --prefix frontend run test:e2e` -> 2 passed (11.8s)
- **Failures**: Configured Playwright `webServer` to use port `8100` (since system port `8000` was occupied) and `channel: 'chrome'`, and synced connection status from DB (`getConnectionStatus`) after job completion so low-credit recovery waits for explicit user refresh.
- **Remaining Work**: Phase 12.

## Phase 12: Evaluation harness, release readiness, and final verification — COMPLETE
- **Implemented Tasks**:
  - Created `benchmark/fixtures/manifest.json` (5 representative renovation evaluation fixtures including preservation lock conflict detection and banned embellishment token list).
  - Created `benchmark/rubric.md` documenting all evaluation criteria.
  - Implemented `benchmark/run.py` (`python benchmark/run.py --mode mock`) verifying prompt compilation fidelity, zero banned tokens, preservation lock conflict blocking, mandatory still image acceptance gate before video quotes, and local FFmpeg `1280x720@30fps` H.264 MP4 assembly.
- **Checks Actually Run**:
  - `PYTHONPATH=backend backend/.venv/bin/pytest backend/tests -v` -> 24 passed in 7.45s
  - `npm --prefix frontend run typecheck && npm --prefix frontend run build` -> Passed
  - `npm --prefix frontend run test:e2e` -> 2 passed in 11.8s
  - `backend/.venv/bin/python benchmark/run.py --mode mock` -> `all_passed: true`, `presentation_valid: true`, `fixtures_evaluated: 5` (exit code 0)
- **Failures**: None.
- **Remaining Work**: None — **offline integration complete; live validation pending.**
