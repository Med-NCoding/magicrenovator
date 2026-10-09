from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any

from app.dependencies import get_db_conn
from app.domain.errors import AppError
from app.domain.schemas import CreateBriefRequest, CreateReviewRequest, ReviewResponse
from app.repositories.jobs import JobRepository
from app.repositories.ledger import LedgerRepository
from app.services.asset_service import AssetService
from app.services.compiler import BriefService
from app.settings import Settings, get_settings


class ReviewService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.asset_service = AssetService(self.settings)
        self.brief_service = BriefService(self.settings)
        self.job_repo = JobRepository(self.settings)
        self.ledger = LedgerRepository(self.settings)

    def submit_review(
        self,
        owner_id_hash: str,
        asset_id: str,
        body: CreateReviewRequest,
    ) -> ReviewResponse:
        asset = self.asset_service.get_asset_owned(owner_id_hash=owner_id_hash, asset_id=asset_id)
        if asset["role"] not in {"generated_image", "generated_video"}:
            raise AppError(
                code="validation_error",
                message="Only generated renovation images or video clips can be reviewed.",
                status_code=400,
                retryable=False,
                next_action="none",
            )

        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT g.*, q.estimated_credits
                    FROM generations g
                    JOIN quotes q ON q.id = g.quote_id
                    WHERE g.output_asset_id = %s AND g.owner_id_hash = %s
                    ORDER BY g.created_at DESC
                    LIMIT 1
                    """,
                    (asset_id, owner_id_hash),
                )
                job_row = cur.fetchone()
                if not job_row:
                    raise AppError(
                        code="not_found",
                        message="Associated generation job not found for this asset.",
                        status_code=404,
                        retryable=False,
                        next_action="none",
                    )
                job = dict(job_row)

                if job["state"] not in {"ready_for_review", "accepted", "rejected"}:
                    raise AppError(
                        code="conflict",
                        message=f"Output asset cannot be reviewed while job is in state '{job['state']}'.",
                        status_code=409,
                        retryable=False,
                        next_action="none",
                    )

                review_id = f"rev_{secrets.token_hex(8)}"
                now = datetime.now(timezone.utc)
                checklist_json = json.dumps(body.checklist.model_dump())

                cur.execute(
                    """
                    INSERT INTO reviews (
                        id, owner_id_hash, project_id, room_id, job_id, brief_revision_id,
                        asset_id, decision, checklist_json, notes, reviewer, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'human_owner', %s)
                    """,
                    (
                        review_id,
                        owner_id_hash,
                        job["project_id"],
                        job["room_id"],
                        job["id"],
                        job["brief_revision_id"],
                        asset_id,
                        body.decision,
                        checklist_json,
                        body.notes,
                        now,
                    ),
                )

                if body.decision == "accept":
                    if asset["role"] == "generated_image":
                        cur.execute(
                            """
                            UPDATE rooms
                            SET accepted_image_asset_id = %s, accepted_image_review_id = %s
                            WHERE id = %s
                            """,
                            (asset_id, review_id, job["room_id"]),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE rooms
                            SET accepted_clip_asset_id = %s, accepted_clip_review_id = %s
                            WHERE id = %s
                            """,
                            (asset_id, review_id, job["room_id"]),
                        )
                    self.ledger.record_event(
                        owner_id_hash=owner_id_hash,
                        account_fingerprint=job.get("account_fingerprint"),
                        job_id=job["id"],
                        quote_id=job["quote_id"],
                        event_type="output_accepted",
                        observed_amount=job.get("observed_credits_charged"),
                        source="review_service",
                        cur=cur,
                    )

        # Transition job state outside the inner cursor block
        if job["state"] == "ready_for_review":
            target_job_state = "accepted" if body.decision == "accept" else "rejected"
            self.job_repo.transition_job(
                job_id=job["id"],
                next_state=target_job_state,
                safe_message=f"Human review decision recorded: {body.decision}.",
                safe_payload={"review_id": review_id, "decision": body.decision},
                clear_lease=True,
            )

        next_brief_id: str | None = None
        next_est_credits: int | None = None

        if body.decision in {"revise", "reject"}:
            next_est_credits = int(job.get("estimated_credits") or 50)
            with get_db_conn(self.settings) as conn:
                with conn.cursor() as cur:
                    if asset["role"] == "generated_image":
                        cur.execute(
                            """
                            UPDATE rooms
                            SET accepted_image_asset_id = NULL, accepted_image_review_id = NULL
                            WHERE id = %s
                            """,
                            (job["room_id"],),
                        )
                    elif asset["role"] == "generated_video":
                        cur.execute(
                            """
                            UPDATE rooms
                            SET accepted_clip_asset_id = NULL, accepted_clip_review_id = NULL
                            WHERE id = %s
                            """,
                            (job["room_id"],),
                        )
                    cur.execute("SELECT * FROM rooms WHERE id = %s", (job["room_id"],))
                    room_row = dict(cur.fetchone())

            if body.decision == "revise":
                base_brief_id = room_row.get("active_brief_revision_id") or job["brief_revision_id"]
                old_brief_row, old_brief, _ = self.brief_service.get_brief_owned(owner_id_hash, base_brief_id)
                note_clean = body.notes.strip() if (body.notes and body.notes.strip()) else ""
                if note_clean:
                    # Use the revision instruction directly so Magic Hour edits the generated reference image without re-applying superseded instructions
                    revised_raw = note_clean[:2000]
                else:
                    revised_raw = old_brief.raw_request[:2000]

                ref_asset_id = (
                    asset_id
                    if asset["role"] == "generated_image"
                    else (old_brief_row.get("accepted_reference_asset_id") or room_row.get("accepted_image_asset_id"))
                )
                all_conflict_tokens = [
                    "doors",
                    "windows",
                    "island",
                    "island position",
                    "appliance",
                    "appliance positions",
                    "ceiling",
                    "ceiling height",
                    "room footprint",
                    "camera viewpoint",
                    "walls",
                    "flooring",
                    "cabinets",
                    "countertops",
                    "lighting",
                    "hardware",
                    "room finish",
                ]
                new_rev = self.brief_service.save_room_brief(
                    owner_id_hash=owner_id_hash,
                    room_id=job["room_id"],
                    body=CreateBriefRequest(
                        raw_text=revised_raw,
                        preserve=old_brief.preserve,
                        layout_mode=old_brief.layout_mode,
                        style=old_brief.style,
                        resolve_conflicts=all_conflict_tokens,
                        parent_revision_id=base_brief_id,
                        accepted_reference_asset_id=ref_asset_id,
                    ),
                )
                if new_rev.has_unresolved_conflicts:
                    new_rev = self.brief_service.save_room_brief(
                        owner_id_hash=owner_id_hash,
                        room_id=job["room_id"],
                        body=CreateBriefRequest(
                            raw_text=revised_raw,
                            preserve=old_brief.preserve,
                            layout_mode=old_brief.layout_mode,
                            style=old_brief.style,
                            resolve_conflicts=list(new_rev.brief.unresolved) + all_conflict_tokens,
                            parent_revision_id=base_brief_id,
                            accepted_reference_asset_id=ref_asset_id,
                        ),
                    )
                next_brief_id = new_rev.id

        return ReviewResponse(
            id=review_id,
            asset_id=asset_id,
            room_id=job["room_id"],
            brief_revision_id=job["brief_revision_id"],
            decision=body.decision,
            checklist=body.checklist,
            notes=body.notes,
            next_brief_revision_id=next_brief_id,
            next_estimated_credits=next_est_credits,
            created_at=now.isoformat(),
        )
