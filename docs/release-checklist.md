# RenoPreview Release & Verification Checklist

## Pre-Release Offline Gates
- [ ] Phase 1: Repository, contracts, migrations, health/ready, session isolation, frontend build
- [ ] Phase 2: Magic Hour connection, AES-GCM Redis vault, balance refresh, disconnect, zero-credit handling
- [ ] Phase 3: Room CRUD (5-room cap), photo upload normalization, EXIF strip, blur advisory, signed private URLs
- [ ] Phase 4: Structured `RenovationBrief`, preservation controls, contradiction detector, deterministic prompt compiler (`reno-brief-v1`)
- [ ] Phase 5: Reviewed model catalog (`mh-catalog-2026-10-03-v1`), tier filtering, quote binding & 5-minute expiry, idempotent transactional admission, ledger reconciliation
- [ ] Phase 6: `MagicHourGateway` and `MockGateway` contract parity, OpenAPI snapshot validation, mock token block in live gateway
- [ ] Phase 7: Durable worker leases, backoff polling, crash recovery, `submission_unknown` reconciliation without automatic replay, SSE + GET snapshot
- [ ] Phase 8: Bounded output download with host allowlist & private IP rejection, media validation, slider + side-by-side comparison, human review checklist
- [ ] Phase 9: Accepted image to video workflow, conservative motion presets, low-credit clip block preserving accepted still image, explicit resume
- [ ] Phase 10: Multi-room FFmpeg presentation assembly (`1280x720@30fps` cuts), sanitized text overlays, contractor handoff Markdown brief export
- [ ] Phase 11: Responsive desktop & mobile layout, keyboard accessibility, reduced motion, `/help` and `/privacy` disclosures
- [ ] Phase 12: Full unit, integration, contract, and Playwright E2E test suites passing; pause switch (`PAUSE_GENERATIONS`) and recovery runbook verified

## Operational Runbook
- **Emergency Pause Switch**: Set `PAUSE_GENERATIONS=true` in environment configuration to immediately block new paid quote admissions and worker submissions while keeping status polling, reviews, and exports active.
- **Ambiguous Submission (`submission_unknown`)**: Instruct user to check their Magic Hour library (`https://magichour.ai/my-library`) for the job's `correlation_name` (`reno_...`) before confirming manual retry with a fresh quote. Never ask for the user's raw API key.
