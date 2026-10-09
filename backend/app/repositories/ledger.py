from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from app.dependencies import get_db_conn
from app.settings import Settings, get_settings

LedgerEventType = Literal[
    "quote_created",
    "spend_authorized",
    "submission_started",
    "provider_charge_observed",
    "charge_reconciled",
    "submission_rejected",
    "output_accepted",
]


class LedgerRepository:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def record_event(
        self,
        owner_id_hash: str,
        event_type: LedgerEventType,
        source: str,
        account_fingerprint: str | None = None,
        job_id: str | None = None,
        attempt_id: str | None = None,
        quote_id: str | None = None,
        estimated_amount: int | None = None,
        observed_amount: int | None = None,
        cur: Any | None = None,
    ) -> dict[str, Any] | None:
        event_id = f"led_{secrets.token_hex(8)}"
        now = datetime.now(timezone.utc)

        def _insert(cursor: Any) -> dict[str, Any] | None:
            if attempt_id is not None:
                cursor.execute(
                    """
                    INSERT INTO credit_ledger (
                        id, owner_id_hash, account_fingerprint, job_id, attempt_id, quote_id,
                        event_type, estimated_amount, observed_amount, source, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (attempt_id, event_type) DO NOTHING
                    RETURNING *
                    """,
                    (
                        event_id,
                        owner_id_hash,
                        account_fingerprint,
                        job_id,
                        attempt_id,
                        quote_id,
                        event_type,
                        estimated_amount,
                        observed_amount,
                        source,
                        now,
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO credit_ledger (
                        id, owner_id_hash, account_fingerprint, job_id, attempt_id, quote_id,
                        event_type, estimated_amount, observed_amount, source, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        event_id,
                        owner_id_hash,
                        account_fingerprint,
                        job_id,
                        attempt_id,
                        quote_id,
                        event_type,
                        estimated_amount,
                        observed_amount,
                        source,
                        now,
                    ),
                )
            row = cursor.fetchone()
            return dict(row) if row else None

        if cur is not None:
            return _insert(cur)
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as db_cur:
                return _insert(db_cur)

    def summarize_owner_ledger(self, owner_id_hash: str) -> dict[str, Any]:
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM credit_ledger
                    WHERE owner_id_hash = %s
                    ORDER BY created_at ASC
                    """,
                    (owner_id_hash,),
                )
                events = [dict(r) for r in cur.fetchall()]

        reconciled_by_attempt: dict[str, int | None] = {}
        accepted_outputs = 0
        has_unknown_charge = False

        for ev in events:
            att_id = ev["attempt_id"]
            ev_type = ev["event_type"]
            obs = ev["observed_amount"]
            if ev_type == "submission_started" and att_id:
                reconciled_by_attempt.setdefault(att_id, None)
            elif ev_type in {"provider_charge_observed", "charge_reconciled"} and att_id:
                if obs is not None:
                    reconciled_by_attempt[att_id] = obs
            elif ev_type == "submission_rejected" and att_id:
                reconciled_by_attempt[att_id] = 0
            elif ev_type == "output_accepted":
                accepted_outputs += 1

        total_observed = 0
        for att_id, amount in reconciled_by_attempt.items():
            if amount is None:
                has_unknown_charge = True
            else:
                total_observed += amount

        cost_per_accepted: float | None = None
        if accepted_outputs > 0 and not has_unknown_charge:
            cost_per_accepted = total_observed / accepted_outputs

        return {
            "total_observed_credits": None if has_unknown_charge else total_observed,
            "known_observed_credits": total_observed,
            "has_unknown_charge": has_unknown_charge,
            "accepted_outputs": accepted_outputs,
            "accepted_output_cost": cost_per_accepted,
            "events": events,
        }
