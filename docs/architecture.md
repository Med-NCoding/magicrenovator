# RenoPreview Architecture

## Component Responsibilities & Boundaries

| Component | Responsibility | Must Not Do |
| :--- | :--- | :--- |
| **React App (`frontend/`)** | Forms, uploads, comparison slider/side-by-side, job progress, review checklist, clip order | Hold permanent provider secrets or call Magic Hour directly |
| **FastAPI (`backend/app/main.py`)** | Session auth, owner checks, input validation, quotes, transactional job + outbox admission | Wait synchronously for long-running image/video generation |
| **Worker (`backend/app/workers/`)** | Outbox dispatch, lease claim, provider submission, polling, bounded download, FFmpeg assembly | Resubmit ambiguous paid work (`submission_unknown`) blindly |
| **Postgres (`backend/migrations/`)** | Projects, rooms, assets, brief revisions, quotes, jobs, attempts, reviews, ledger, outbox | Store raw Magic Hour API keys or plaintext session tokens |
| **Redis** | AES-GCM encrypted credential TTL vault, rate limits, per-account admission/submission locks | Act as the only durable job store |
| **Private Asset Store** | Normalized room photos, thumbnails, validated provider outputs, assembled MP4s, brief exports | Publish home photos publicly by default or accept client storage paths |
| **Magic Hour Gateway (`gateways/`)** | Provider request/response normalization and error mapping | Decide app permissions or project ownership |
| **Prompt Compiler (`services/compiler.py`)** | Brief validation, conflict detection, deterministic prompt construction | Invent unrequested construction scope or material embellishments |

## Transaction & Recovery Boundaries
1. **Admission Transaction**: Validates session owner, active brief revision, quote expiry and `spec_hash`, model catalog compatibility, and `(owner_id_hash, idempotency_key)` uniqueness. Atomically inserts the `generations` record, initial `job_events` entry, `spend_authorized` ledger record, and `outbox` event.
2. **Distributed Submission Boundary**: The worker claims a job lease, resolves the encrypted credential from Redis, rechecks live provider balance under the account fingerprint lock, uploads normalized source bytes to Magic Hour storage, records `submitting` state, and calls Magic Hour once.
3. **Ambiguous Submission (`submission_unknown`)**: If the HTTP call experiences a transport error, 5xx response, or 2xx response missing a string `id`, the worker transitions the job to `submission_unknown`. It never automatically replays a paid creation call.
4. **Polling & Output Recovery**: Once `provider_id` is persisted, polling uses capped exponential backoff with jitter. Network timeouts during polling preserve `provider_id` and retry reads without failing the job. Output download failures transition to `saving_output` / retry download only without regenerating.
