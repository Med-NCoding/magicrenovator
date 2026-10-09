from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.dependencies import get_db_conn
from app.domain.errors import AppError, redact_secrets
from app.domain.states import validate_state_transition
from app.settings import Settings, get_settings


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


class JobRepository:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def append_job_event(
        self,
        cur: Any,
        job_id: str,
        state: str,
        safe_message: str,
        safe_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        clean_msg = redact_secrets(safe_message)
        payload_str = redact_secrets(json.dumps(safe_payload or {}, sort_keys=True))
        cur.execute(
            """
            INSERT INTO job_events (job_id, state, safe_message, safe_payload_json, created_at)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (job_id, state, clean_msg, payload_str, now),
        )
        return dict(cur.fetchone())

    def get_job_owned(self, owner_id_hash: str, job_id: str) -> dict[str, Any]:
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT g.*, q.estimated_credits, r.active_brief_revision_id AS room_active_brief_id
                    FROM generations g
                    JOIN quotes q ON q.id = g.quote_id
                    JOIN rooms r ON r.id = g.room_id
                    JOIN projects p ON p.id = g.project_id
                    WHERE g.id = %s AND g.owner_id_hash = %s AND p.deleted_at IS NULL
                    """,
                    (job_id, owner_id_hash),
                )
                row = cur.fetchone()
                if not row:
                    raise AppError(
                        code="not_found",
                        message="Generation job not found.",
                        status_code=404,
                        retryable=False,
                        next_action="none",
                    )
                job = dict(row)
                cur.execute(
                    """
                    SELECT sequence, job_id, state, safe_message, safe_payload_json, created_at
                    FROM job_events
                    WHERE job_id = %s
                    ORDER BY sequence ASC
                    """,
                    (job_id,),
                )
                job["events"] = [dict(ev) for ev in cur.fetchall()]
                return job

    def list_job_events_since(self, owner_id_hash: str, job_id: str, last_sequence: int = 0) -> list[dict[str, Any]]:
        self.get_job_owned(owner_id_hash, job_id)
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT sequence, job_id, state, safe_message, safe_payload_json, created_at
                    FROM job_events
                    WHERE job_id = %s AND sequence > %s
                    ORDER BY sequence ASC
                    """,
                    (job_id, last_sequence),
                )
                return [dict(ev) for ev in cur.fetchall()]

    def transition_job(
        self,
        job_id: str,
        next_state: str,
        safe_message: str,
        provider_state: str | None = None,
        provider_id: str | None = None,
        observed_credits_charged: int | None = None,
        output_asset_id: str | None = None,
        next_poll_at: datetime | None = None,
        last_safe_error: dict[str, Any] | None = None,
        clear_lease: bool = False,
        safe_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM generations WHERE id = %s FOR UPDATE", (job_id,))
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Job {job_id} not found")
                current_state = row["state"]
                has_provider_id = bool(row["provider_id"] or provider_id)
                validate_state_transition(current_state, next_state, has_provider_id=has_provider_id)

                new_provider_id = provider_id or row["provider_id"]
                new_provider_state = provider_state if provider_state is not None else row["provider_state"]
                new_observed = (
                    observed_credits_charged
                    if observed_credits_charged is not None
                    else row["observed_credits_charged"]
                )
                new_output_asset_id = output_asset_id or row["output_asset_id"]
                err_json = (
                    redact_secrets(json.dumps(last_safe_error))
                    if last_safe_error is not None
                    else row["last_safe_error_json"]
                )
                lease_owner = None if clear_lease else row["lease_owner"]
                lease_expires = None if clear_lease else row["lease_expires_at"]

                cur.execute(
                    """
                    UPDATE generations
                    SET state = %s,
                        provider_state = %s,
                        provider_id = %s,
                        observed_credits_charged = %s,
                        output_asset_id = %s,
                        next_poll_at = %s,
                        last_safe_error_json = %s,
                        lease_owner = %s,
                        lease_expires_at = %s,
                        updated_at = %s
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        next_state,
                        new_provider_state,
                        new_provider_id,
                        new_observed,
                        new_output_asset_id,
                        next_poll_at,
                        err_json,
                        lease_owner,
                        lease_expires,
                        now,
                        job_id,
                    ),
                )
                updated = dict(cur.fetchone())
                self.append_job_event(cur, job_id, next_state, safe_message, safe_payload)
                return updated
