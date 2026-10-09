from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any

from app.dependencies import get_db_conn
from app.domain.errors import AppError
from app.domain.schemas import CreateGenerationRequest, GenerationAdmissionResponse
from app.domain.states import ACTIVE_PROVIDER_STATES
from app.repositories.jobs import JobRepository
from app.repositories.ledger import LedgerRepository
from app.services.credential_vault import CredentialVaultService
from app.services.quote_service import compute_quote_spec_hash
from app.settings import Settings, get_settings


class AdmissionService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.vault = CredentialVaultService(self.settings)
        self.job_repo = JobRepository(self.settings)
        self.ledger = LedgerRepository(self.settings)

    def admit_generation(
        self,
        owner_id_hash: str,
        body: CreateGenerationRequest,
    ) -> tuple[GenerationAdmissionResponse, bool]:
        if self.settings.PAUSE_GENERATIONS:
            raise AppError(
                code="provider_unavailable",
                message="Paid generations are temporarily paused by operator kill switch.",
                status_code=503,
                retryable=True,
                next_action="wait_and_retry",
            )

        idempotency_key = body.idempotency_key.strip()
        quote_id = body.quote_id.strip()
        request_hash = hashlib.sha256(f"{owner_id_hash}:{quote_id}".encode("utf-8")).hexdigest()

        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                # Serialize concurrent requests with the same (owner_id_hash, idempotency_key)
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (f"idemp:{owner_id_hash}:{idempotency_key}",),
                )
                cur.execute(
                    """
                    SELECT * FROM generations
                    WHERE owner_id_hash = %s AND idempotency_key = %s
                    """,
                    (owner_id_hash, idempotency_key),
                )
                existing_job = cur.fetchone()
                if existing_job:
                    if existing_job["request_hash"] != request_hash:
                        raise AppError(
                            code="conflict",
                            message="Idempotency key was already used with a different quote or request payload.",
                            status_code=409,
                            retryable=False,
                            next_action="new_idempotency_key",
                        )
                    return (
                        GenerationAdmissionResponse(
                            job_id=existing_job["id"],
                            state=existing_job["state"],
                            status_route=f"/api/generations/{existing_job['id']}",
                            events_route=f"/api/generations/{existing_job['id']}/events",
                            quote_id=existing_job["quote_id"],
                            idempotency_key=existing_job["idempotency_key"],
                        ),
                        False,
                    )

                # Lock the quote row
                cur.execute(
                    """
                    SELECT * FROM quotes
                    WHERE id = %s AND owner_id_hash = %s
                    FOR UPDATE
                    """,
                    (quote_id, owner_id_hash),
                )
                quote_row = cur.fetchone()
                if not quote_row:
                    raise AppError(
                        code="not_found",
                        message="Quote not found.",
                        status_code=404,
                        retryable=False,
                        next_action="create_new_quote",
                    )
                quote = dict(quote_row)

                if quote.get("consumed_by_job_id"):
                    raise AppError(
                        code="conflict",
                        message="This quote has already been used to start a generation. Request a new quote to generate again.",
                        status_code=409,
                        retryable=False,
                        next_action="create_new_quote",
                    )

                now = datetime.now(timezone.utc)
                expires_at = quote["expires_at"]
                if isinstance(expires_at, str):
                    expires_at = datetime.fromisoformat(expires_at)
                if expires_at < now:
                    raise AppError(
                        code="stale_quote",
                        message="This credit quote has expired. Please refresh the quote before starting generation.",
                        status_code=409,
                        retryable=True,
                        next_action="refresh_quote",
                    )

                # Verify brief revision and room state still match the quote's spec_hash
                cur.execute("SELECT * FROM rooms WHERE id = %s AND deleted_at IS NULL", (quote["room_id"],))
                room_row = cur.fetchone()
                cur.execute("SELECT * FROM brief_revisions WHERE id = %s", (quote["brief_revision_id"],))
                brief_row = cur.fetchone()
                if not room_row or not brief_row:
                    raise AppError(
                        code="not_found",
                        message="Room or brief revision not found.",
                        status_code=404,
                        retryable=False,
                        next_action="none",
                    )
                room = dict(room_row)
                brief_rev = dict(brief_row)

                if room.get("active_brief_revision_id") != brief_rev["id"]:
                    raise AppError(
                        code="stale_quote",
                        message="The room renovation brief was updated after this quote was created. Refresh the quote.",
                        status_code=409,
                        retryable=True,
                        next_action="refresh_quote",
                    )
                if quote["kind"] == "image":
                    if room.get("primary_asset_id") != quote["source_asset_id"]:
                        raise AppError(
                            code="stale_quote",
                            message="The room reference photo was replaced after this quote was created. Refresh the quote.",
                            status_code=409,
                            retryable=True,
                            next_action="refresh_quote",
                        )
                else:
                    if quote.get("source_review_id") is not None:
                        if (
                            room.get("accepted_image_asset_id") != quote["source_asset_id"]
                            or room.get("accepted_image_review_id") != quote.get("source_review_id")
                        ):
                            raise AppError(
                                code="stale_quote",
                                message="The accepted room image changed after this quote was created. Refresh the video quote.",
                                status_code=409,
                                retryable=True,
                                next_action="refresh_quote",
                            )
                    else:
                        valid_sources = {
                            room.get("primary_asset_id"),
                            room.get("accepted_image_asset_id"),
                            brief_rev.get("accepted_reference_asset_id"),
                            brief_rev.get("source_asset_id"),
                        }
                        if quote["source_asset_id"] not in valid_sources:
                            raise AppError(
                                code="stale_quote",
                                message="The room reference photo changed after this quote was created. Refresh the video quote.",
                                status_code=409,
                                retryable=True,
                                next_action="refresh_quote",
                            )

                recomputed_hash = compute_quote_spec_hash(
                    brief_revision_id=brief_rev["id"],
                    brief_source_hash=brief_rev["source_hash"],
                    source_asset_id=quote["source_asset_id"],
                    kind=quote["kind"],
                    model=quote["model"],
                    resolution=quote["resolution"],
                    image_count=int(quote["image_count"]),
                    duration_seconds=quote.get("duration_seconds"),
                    audio=bool(quote.get("audio", False)),
                    motion_preset=quote.get("motion_preset"),
                    catalog_version=quote["catalog_version"],
                )
                if recomputed_hash != quote["spec_hash"]:
                    raise AppError(
                        code="stale_quote",
                        message="Quote specification hash mismatch. Please request a fresh quote.",
                        status_code=409,
                        retryable=True,
                        next_action="refresh_quote",
                    )

                # Verify active Magic Hour credential and credit balance
                _, ref = self.vault.resolve_key_for_owner(owner_id_hash)
                account_fingerprint = str(ref["provider_account_fingerprint"])
                current_credits = int(ref["balance"])
                required_credits = int(quote["estimated_credits"])

                if current_credits < required_credits or int(quote["balance_snapshot"]) < required_credits:
                    raise AppError(
                        code="insufficient_credits",
                        message=(
                            f"Insufficient Magic Hour credits ({current_credits} available, "
                            f"{required_credits} required). Top up credits and refresh your balance."
                        ),
                        status_code=402,
                        retryable=True,
                        next_action="top_up_credits",
                    )

                # Serialize per-account active job concurrency check
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (f"acct:{account_fingerprint}",),
                )
                active_states = tuple(ACTIVE_PROVIDER_STATES)
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt FROM generations
                    WHERE account_fingerprint = %s AND state IN %s
                    """,
                    (account_fingerprint, active_states),
                )
                active_cnt = int(cur.fetchone()["cnt"])
                if active_cnt >= self.settings.MAX_ACTIVE_JOBS_PER_ACCOUNT:
                    raise AppError(
                        code="conflict",
                        message=(
                            "Another generation is currently active for this Magic Hour account. "
                            "Wait for the active job to complete before starting a new one."
                        ),
                        status_code=409,
                        retryable=True,
                        next_action="wait_for_active_job",
                    )

                job_id = f"job_{secrets.token_hex(8)}"
                outbox_id = f"obx_{secrets.token_hex(8)}"
                correlation_name = f"renopreview:{room['id']}:{job_id}:{brief_rev['id']}"[:120]

                options_payload = {
                    "resolution": quote["resolution"],
                    "image_count": int(quote["image_count"]),
                    "duration_seconds": quote.get("duration_seconds"),
                    "audio": bool(quote.get("audio", False)),
                    "motion_preset": quote.get("motion_preset"),
                }
                compiled_prompt = (
                    quote["motion_prompt"]
                    if (quote["kind"] == "video" and quote.get("motion_prompt"))
                    else brief_rev["compiled_prompt"]
                )

                cur.execute(
                    """
                    INSERT INTO generations (
                        id, owner_id_hash, project_id, room_id, brief_revision_id, quote_id,
                        idempotency_key, request_hash, kind, state, source_asset_id, source_review_id,
                        model, options_json, compiled_prompt, compiler_version, catalog_version,
                        correlation_name, account_fingerprint, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'admitted', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        job_id,
                        owner_id_hash,
                        quote["project_id"],
                        quote["room_id"],
                        quote["brief_revision_id"],
                        quote_id,
                        idempotency_key,
                        request_hash,
                        quote["kind"],
                        quote["source_asset_id"],
                        quote.get("source_review_id"),
                        quote["model"],
                        json.dumps(options_payload),
                        compiled_prompt,
                        brief_rev["compiler_version"],
                        quote["catalog_version"],
                        correlation_name,
                        account_fingerprint,
                        now,
                        now,
                    ),
                )

                cur.execute(
                    """
                    UPDATE quotes
                    SET confirmed_at = %s, consumed_by_job_id = %s
                    WHERE id = %s
                    """,
                    (now, job_id, quote_id),
                )
                cur.execute(
                    "UPDATE brief_revisions SET submitted = TRUE WHERE id = %s",
                    (brief_rev["id"],),
                )

                self.job_repo.append_job_event(
                    cur=cur,
                    job_id=job_id,
                    state="admitted",
                    safe_message="Quote confirmed and generation admitted for provider submission.",
                    safe_payload={
                        "quote_id": quote_id,
                        "kind": quote["kind"],
                        "model": quote["model"],
                        "resolution": quote["resolution"],
                        "estimated_credits": required_credits,
                    },
                )

                self.ledger.record_event(
                    owner_id_hash=owner_id_hash,
                    account_fingerprint=account_fingerprint,
                    job_id=job_id,
                    quote_id=quote_id,
                    event_type="spend_authorized",
                    estimated_amount=required_credits,
                    source="admission_service",
                    cur=cur,
                )

                cur.execute(
                    """
                    INSERT INTO outbox (id, job_id, event_type, payload_json, dispatched, created_at)
                    VALUES (%s, %s, 'submit_generation', %s, FALSE, %s)
                    """,
                    (outbox_id, job_id, json.dumps({"job_id": job_id}), now),
                )

                return (
                    GenerationAdmissionResponse(
                        job_id=job_id,
                        state="admitted",
                        status_route=f"/api/generations/{job_id}",
                        events_route=f"/api/generations/{job_id}/events",
                        quote_id=quote_id,
                        idempotency_key=idempotency_key,
                    ),
                    True,
                )
