from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import StreamingResponse

from app.dependencies import SessionOwner, get_db_conn, require_csrf, require_owner
from app.domain.errors import AppError
from app.domain.schemas import (
    CreateGenerationRequest,
    GenerationAdmissionResponse,
    GenerationSnapshotResponse,
    JobEventRecord,
    ResumeGenerationRequest,
)
from app.domain.states import PERMITTED_NEXT_ACTIONS, TERMINAL_JOB_STATES
from app.repositories.jobs import JobRepository
from app.services.admission import AdmissionService
from app.services.asset_service import sign_asset_url
from app.services.credential_vault import CredentialVaultService
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/generations", tags=["generations"])


def format_generation_snapshot(
    job: dict[str, Any],
    owner_id_hash: str,
    settings: Settings,
) -> GenerationSnapshotResponse:
    opts = job.get("options_json") or {}
    if isinstance(opts, str):
        opts = json.loads(opts)
    last_err = job.get("last_safe_error_json")
    if isinstance(last_err, str) and last_err:
        try:
            last_err = json.loads(last_err)
        except Exception:
            last_err = {"message": last_err}
    elif not isinstance(last_err, dict):
        last_err = None

    events_out: list[JobEventRecord] = []
    for ev in job.get("events", []):
        payload = ev.get("safe_payload_json") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        ts = ev["created_at"]
        ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
        events_out.append(
            JobEventRecord(
                sequence=int(ev["sequence"]),
                job_id=ev["job_id"],
                state=ev["state"],
                safe_message=ev["safe_message"],
                timestamp=ts_str,
                payload=payload,
            )
        )

    source_id = job["source_asset_id"]
    out_id = job.get("output_asset_id")
    created_at = job["created_at"]
    updated_at = job["updated_at"]
    state_str = str(job["state"])
    room_active_brief = job.get("room_active_brief_id")
    brief_outdated = bool(room_active_brief and room_active_brief != job["brief_revision_id"])

    return GenerationSnapshotResponse(
        job_id=job["id"],
        project_id=job["project_id"],
        room_id=job["room_id"],
        brief_revision_id=job["brief_revision_id"],
        quote_id=job["quote_id"],
        kind=job["kind"],
        state=state_str,
        provider_state=job.get("provider_state"),
        permitted_next_action=PERMITTED_NEXT_ACTIONS.get(state_str, "none"),
        model=job["model"],
        resolution=str(opts.get("resolution", "1k")),
        source_asset_id=source_id,
        source_asset_url=sign_asset_url(source_id, owner_id_hash, settings) if source_id else None,
        output_asset_id=out_id,
        output_asset_url=sign_asset_url(out_id, owner_id_hash, settings) if out_id else None,
        brief_outdated=brief_outdated,
        estimated_credits=int(job.get("estimated_credits") or 0),
        observed_credits_charged=job.get("observed_credits_charged"),
        correlation_name=job["correlation_name"],
        provider_id=job.get("provider_id"),
        last_safe_error=last_err,
        created_at=created_at.isoformat() if isinstance(created_at, datetime) else str(created_at),
        updated_at=updated_at.isoformat() if isinstance(updated_at, datetime) else str(updated_at),
        events=events_out,
    )


@router.post("", response_model=GenerationAdmissionResponse, status_code=201)
def create_generation(
    body: CreateGenerationRequest,
    response: Response,
    owner: SessionOwner = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
) -> GenerationAdmissionResponse:
    svc = AdmissionService(settings)
    admission_res, is_new = svc.admit_generation(owner_id_hash=owner.id_hash, body=body)
    if not is_new:
        response.status_code = 200
    return admission_res


@router.get("/{job_id}", response_model=GenerationSnapshotResponse)
def get_generation(
    job_id: str,
    owner: SessionOwner = Depends(require_owner),
    settings: Settings = Depends(get_settings),
) -> GenerationSnapshotResponse:
    repo = JobRepository(settings)
    job = repo.get_job_owned(owner_id_hash=owner.id_hash, job_id=job_id)
    return format_generation_snapshot(job, owner.id_hash, settings)


@router.get("/{job_id}/events")
def stream_generation_events(
    job_id: str,
    last_event_id_query: int = Query(default=0, alias="last_event_id"),
    last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
    owner: SessionOwner = Depends(require_owner),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    repo = JobRepository(settings)
    last_seq = last_event_id_query
    if last_event_id_header and last_event_id_header.strip().isdigit():
        last_seq = max(last_seq, int(last_event_id_header.strip()))

    events = repo.list_job_events_since(owner_id_hash=owner.id_hash, job_id=job_id, last_sequence=last_seq)

    def _event_generator():
        for ev in events:
            payload = ev.get("safe_payload_json") or "{}"
            if isinstance(payload, str):
                try:
                    payload_obj = json.loads(payload)
                except Exception:
                    payload_obj = {}
            else:
                payload_obj = payload
            ts = ev["created_at"]
            record = {
                "sequence": int(ev["sequence"]),
                "job_id": ev["job_id"],
                "state": ev["state"],
                "safe_message": ev["safe_message"],
                "timestamp": ts.isoformat() if isinstance(ts, datetime) else str(ts),
                "payload": payload_obj,
            }
            yield f"id: {ev['sequence']}\nevent: job_state\ndata: {json.dumps(record)}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{job_id}/stop", response_model=GenerationSnapshotResponse)
def stop_generation(
    job_id: str,
    owner: SessionOwner = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
) -> GenerationSnapshotResponse:
    repo = JobRepository(settings)
    job = repo.get_job_owned(owner_id_hash=owner.id_hash, job_id=job_id)
    if job["state"] in TERMINAL_JOB_STATES:
        return format_generation_snapshot(job, owner.id_hash, settings)

    repo.transition_job(
        job_id=job_id,
        next_state="stopped",
        safe_message=(
            "Local polling and worker updates stopped by user. "
            "Note: any job already submitted to Magic Hour remains governed by Magic Hour's processing."
        ),
        clear_lease=True,
    )
    updated = repo.get_job_owned(owner_id_hash=owner.id_hash, job_id=job_id)
    return format_generation_snapshot(updated, owner.id_hash, settings)


@router.post("/{job_id}/resume", response_model=GenerationSnapshotResponse)
def resume_generation(
    job_id: str,
    body: ResumeGenerationRequest,
    owner: SessionOwner = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
) -> GenerationSnapshotResponse:
    repo = JobRepository(settings)
    vault = CredentialVaultService(settings)
    job = repo.get_job_owned(owner_id_hash=owner.id_hash, job_id=job_id)
    state = job["state"]
    now = datetime.now(timezone.utc)

    # Verify key is connected
    _, ref = vault.resolve_key_for_owner(owner.id_hash)

    if state == "waiting_for_key":
        next_st = "queued" if job.get("provider_id") else "preparing"
        repo.transition_job(
            job_id=job_id,
            next_state=next_st,
            safe_message="Magic Hour key reconnected; resuming generation workflow.",
            next_poll_at=now,
            clear_lease=True,
        )
    elif state == "blocked_credits":
        if int(ref["balance"]) < int(job["estimated_credits"]):
            raise AppError(
                code="insufficient_credits",
                message="Credit balance is still below the required amount. Top up and refresh balance first.",
                status_code=402,
                retryable=True,
                next_action="top_up_credits",
            )
        repo.transition_job(
            job_id=job_id,
            next_state="preparing",
            safe_message="Credit balance verified; resuming pre-submission preparation.",
            next_poll_at=now,
            clear_lease=True,
        )
    elif state == "failed" and job.get("provider_id") and not job.get("output_asset_id"):
        # Download-only retry without re-charging provider
        repo.transition_job(
            job_id=job_id,
            next_state="saving_output",
            safe_message="Retrying output download for completed provider job without re-submitting.",
            next_poll_at=now,
            clear_lease=True,
        )
    elif state == "submission_unknown":
        if job.get("provider_id"):
            repo.transition_job(
                job_id=job_id,
                next_state="queued",
                safe_message="Provider project ID reconciled; resuming status polling without paid replay.",
                next_poll_at=now,
                clear_lease=True,
            )
        elif body.confirm_not_in_dashboard and body.quote_id:
            # User explicitly verified no job exists in Magic Hour dashboard and supplied a fresh quote
            repo.transition_job(
                job_id=job_id,
                next_state="stopped",
                safe_message="Ambiguous submission closed by user confirmation before creating a new quote job.",
                clear_lease=True,
            )
        else:
            raise AppError(
                code="submission_unknown",
                message=(
                    f"Submission outcome for correlation '{job['correlation_name']}' is ambiguous. "
                    "Verify in your Magic Hour dashboard before starting a new paid submission."
                ),
                status_code=409,
                retryable=False,
                next_action="reconcile_without_paid_replay",
            )
    else:
        raise AppError(
            code="conflict",
            message=f"Job in state '{state}' cannot be resumed directly.",
            status_code=409,
            retryable=False,
            next_action=PERMITTED_NEXT_ACTIONS.get(state, "none"),
        )

    updated = repo.get_job_owned(owner_id_hash=owner.id_hash, job_id=job_id)
    return format_generation_snapshot(updated, owner.id_hash, settings)
