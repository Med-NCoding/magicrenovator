from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
import httpx

from app.dependencies import get_db_conn, get_gateway
from app.gateways.base import ProviderGateway
from app.settings import Settings, get_settings
from app.workers.poll import poll_job
from app.workers.submit import submit_job

LEASE_DURATION_SECONDS = 30


def claim_due_jobs(
    worker_id: str,
    limit: int = 5,
    settings: Settings | None = None,
    specific_job_id: str | None = None,
) -> list[dict[str, Any]]:
    cfg = settings or get_settings()
    now = datetime.now(timezone.utc)
    lease_until = now + timedelta(seconds=LEASE_DURATION_SECONDS)

    with get_db_conn(cfg) as conn:
        with conn.cursor() as cur:
            if specific_job_id:
                cur.execute(
                    """
                    SELECT id, state FROM generations
                    WHERE id = %s
                      AND state IN ('admitted', 'preparing', 'submitting', 'queued', 'rendering', 'saving_output')
                      AND (lease_expires_at IS NULL OR lease_expires_at <= %s)
                    FOR UPDATE SKIP LOCKED
                    """,
                    (specific_job_id, now),
                )
            else:
                cur.execute(
                    """
                    SELECT id, state FROM generations
                    WHERE state IN ('admitted', 'preparing', 'submitting', 'queued', 'rendering', 'saving_output')
                      AND (lease_expires_at IS NULL OR lease_expires_at <= %s)
                      AND (next_poll_at IS NULL OR next_poll_at <= %s)
                    ORDER BY created_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                    """,
                    (now, now, limit),
                )
            rows = [dict(r) for r in cur.fetchall()]
            claimed: list[dict[str, Any]] = []
            for r in rows:
                cur.execute(
                    """
                    UPDATE generations
                    SET lease_owner = %s, lease_expires_at = %s, updated_at = %s
                    WHERE id = %s
                    RETURNING *
                    """,
                    (worker_id, lease_until, now, r["id"]),
                )
                claimed.append(dict(cur.fetchone()))
                cur.execute(
                    """
                    UPDATE outbox
                    SET dispatched = TRUE, dispatched_at = %s
                    WHERE job_id = %s AND dispatched = FALSE
                    """,
                    (now, r["id"]),
                )
            return claimed


def force_expire_lease(job_id: str, settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    with get_db_conn(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE generations
                SET lease_expires_at = %s, next_poll_at = %s
                WHERE id = %s
                """,
                (past, past, job_id),
            )


async def process_claimed_job(
    job: dict[str, Any],
    settings: Settings | None = None,
    gateway: ProviderGateway | None = None,
    http_client: httpx.AsyncClient | None = None,
    crash_point: str | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    gw = gateway or get_gateway(cfg)
    state = job["state"]
    job_id = job["id"]

    if state in {"admitted", "preparing", "submitting"}:
        return await submit_job(
            job_id=job_id,
            settings=cfg,
            gateway=gw,
            crash_point=crash_point,
        )
    if state in {"queued", "rendering", "saving_output"}:
        return await poll_job(
            job_id=job_id,
            settings=cfg,
            gateway=gw,
            http_client=http_client,
            crash_point=crash_point,
        )
    return job


async def run_worker_once(
    settings: Settings | None = None,
    gateway: ProviderGateway | None = None,
    http_client: httpx.AsyncClient | None = None,
    crash_point: str | None = None,
    specific_job_id: str | None = None,
) -> list[dict[str, Any]]:
    cfg = settings or get_settings()
    worker_id = f"wrk_{secrets.token_hex(4)}"
    claimed = claim_due_jobs(
        worker_id=worker_id,
        settings=cfg,
        specific_job_id=specific_job_id,
    )
    results: list[dict[str, Any]] = []
    for job in claimed:
        updated = await process_claimed_job(
            job=job,
            settings=cfg,
            gateway=gateway,
            http_client=http_client,
            crash_point=crash_point,
        )
        results.append(updated)

    # Also process any queued presentation exports if assemble module is present
    try:
        from app.workers.assemble import run_pending_exports_once

        await run_pending_exports_once(settings=cfg)
    except ImportError:
        pass

    return results


async def run_job_until_settled(
    job_id: str,
    max_ticks: int = 10,
    settings: Settings | None = None,
    gateway: ProviderGateway | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    settled_states = {
        "waiting_for_key",
        "blocked_credits",
        "submission_unknown",
        "ready_for_review",
        "accepted",
        "rejected",
        "failed",
        "stopped",
    }
    latest: dict[str, Any] = {}
    for _ in range(max_ticks):
        force_expire_lease(job_id, settings=cfg)
        res = await run_worker_once(
            settings=cfg,
            gateway=gateway,
            http_client=http_client,
            specific_job_id=job_id,
        )
        if res:
            latest = res[0]
            if latest["state"] in settled_states:
                return latest
        else:
            with get_db_conn(cfg) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM generations WHERE id = %s", (job_id,))
                    row = cur.fetchone()
                    if row:
                        latest = dict(row)
                        if latest["state"] in settled_states:
                            return latest
    return latest


async def main_worker_loop() -> None:
    cfg = get_settings()
    while True:
        try:
            await run_worker_once(settings=cfg)
        except Exception:
            pass
        await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main_worker_loop())
