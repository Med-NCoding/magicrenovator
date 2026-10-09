from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import httpx

from app.dependencies import get_db_conn, get_gateway
from app.domain.errors import AppError, redact_secrets
from app.gateways.base import (
    ProviderGateway,
    ProviderRejected,
    ProviderUnavailable,
)
from app.repositories.jobs import JobRepository
from app.repositories.ledger import LedgerRepository
from app.services.credential_vault import CredentialVaultService
from app.settings import Settings, get_settings
from app.workers.download import download_and_save_output


async def poll_job(
    job_id: str,
    settings: Settings | None = None,
    gateway: ProviderGateway | None = None,
    http_client: httpx.AsyncClient | None = None,
    crash_point: str | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    gw = gateway or get_gateway(cfg)
    job_repo = JobRepository(cfg)
    ledger = LedgerRepository(cfg)
    vault = CredentialVaultService(cfg)

    with get_db_conn(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM generations WHERE id = %s", (job_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Job {job_id} not found")
            job = dict(row)

    if job["state"] not in {"queued", "rendering", "saving_output"}:
        return job

    if not job.get("provider_id"):
        return job_repo.transition_job(
            job_id=job_id,
            next_state="submission_unknown",
            safe_message="Cannot poll job without a recorded provider ID.",
            clear_lease=True,
        )

    try:
        raw_key, ref = vault.resolve_key_for_owner(job["owner_id_hash"])
    except AppError as exc:
        if exc.code in {"not_connected", "invalid_key"}:
            return job_repo.transition_job(
                job_id=job_id,
                next_state="waiting_for_key",
                safe_message="Magic Hour key expired or disconnected while polling; reconnect key to resume polling.",
                clear_lease=True,
            )
        raise

    now = datetime.now(timezone.utc)
    try:
        status = await gw.get_project_status(
            key=raw_key,
            kind=job["kind"],
            provider_id=job["provider_id"],
        )
    except ProviderUnavailable as exc:
        next_attempt = int(job.get("attempt_count") or 0) + 1
        backoff_sec = min(30, 2 ** min(next_attempt, 5))
        next_poll = now + timedelta(seconds=backoff_sec)
        with get_db_conn(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE generations
                    SET attempt_count = %s,
                        next_poll_at = %s,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        updated_at = %s
                    WHERE id = %s
                    RETURNING *
                    """,
                    (next_attempt, next_poll, now, job_id),
                )
                return dict(cur.fetchone())
    except ProviderRejected as exc:
        if exc.status == 401:
            return job_repo.transition_job(
                job_id=job_id,
                next_state="waiting_for_key",
                safe_message="Magic Hour rejected key during status poll (401); reconnect a valid key.",
                clear_lease=True,
            )
        return job_repo.transition_job(
            job_id=job_id,
            next_state="failed",
            safe_message=f"Provider status check failed ({exc.code}).",
            last_safe_error={"code": exc.code, "message": redact_secrets(exc.message), "retryable": False},
            clear_lease=True,
        )

    # Reconcile observed credits if reported on status
    if status.credits_charged is not None:
        with get_db_conn(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM provider_attempts
                    WHERE job_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (job_id,),
                )
                att_row = cur.fetchone()
                if att_row:
                    ledger.record_event(
                        owner_id_hash=job["owner_id_hash"],
                        account_fingerprint=job.get("account_fingerprint"),
                        job_id=job_id,
                        attempt_id=att_row["id"],
                        quote_id=job["quote_id"],
                        event_type="charge_reconciled",
                        observed_amount=status.credits_charged,
                        source="poll_worker",
                        cur=cur,
                    )

    if status.status in {"draft", "queued"}:
        next_poll = now + timedelta(seconds=1)
        with get_db_conn(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE generations
                    SET provider_state = %s,
                        observed_credits_charged = COALESCE(%s, observed_credits_charged),
                        next_poll_at = %s,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        updated_at = %s
                    WHERE id = %s
                    RETURNING *
                    """,
                    (status.status, status.credits_charged, next_poll, now, job_id),
                )
                return dict(cur.fetchone())

    if status.status == "rendering":
        next_poll = now + timedelta(seconds=1)
        if job["state"] != "rendering":
            return job_repo.transition_job(
                job_id=job_id,
                next_state="rendering",
                provider_state="rendering",
                observed_credits_charged=status.credits_charged,
                next_poll_at=next_poll,
                safe_message="Magic Hour is rendering the renovation output.",
                clear_lease=True,
            )
        with get_db_conn(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE generations
                    SET provider_state = 'rendering',
                        observed_credits_charged = COALESCE(%s, observed_credits_charged),
                        next_poll_at = %s,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        updated_at = %s
                    WHERE id = %s
                    RETURNING *
                    """,
                    (status.credits_charged, next_poll, now, job_id),
                )
                return dict(cur.fetchone())

    if status.status in {"error", "canceled"}:
        return job_repo.transition_job(
            job_id=job_id,
            next_state="failed",
            provider_state=status.status,
            observed_credits_charged=status.credits_charged,
            safe_message=f"Provider reported {status.status}: {status.error_message or status.error_code or 'generation failed'}.",
            last_safe_error={
                "code": status.error_code or status.status,
                "message": status.error_message or f"Provider job ended with status {status.status}.",
                "retryable": False,
            },
            clear_lease=True,
        )

    # status.status == "complete"
    if job["state"] != "saving_output":
        job = job_repo.transition_job(
            job_id=job_id,
            next_state="saving_output",
            provider_state="complete",
            observed_credits_charged=status.credits_charged,
            safe_message="Provider generation complete; downloading and verifying output media.",
        )

    if crash_point == "after_complete_before_download":
        raise RuntimeError("Simulated crash after provider complete before download")

    if not status.downloads:
        return job_repo.transition_job(
            job_id=job_id,
            next_state="failed",
            safe_message="Provider reported completion without a download URL.",
            last_safe_error={"code": "save_failed", "message": "Missing download URL on completed provider job.", "retryable": True},
            clear_lease=True,
        )

    return await download_and_save_output(
        job_id=job_id,
        download_url=status.downloads[0].url,
        settings=cfg,
        http_client=http_client,
    )
