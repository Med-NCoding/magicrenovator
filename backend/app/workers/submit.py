from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timezone
from typing import Any

from app.dependencies import get_db_conn, get_gateway
from app.domain.errors import AppError, redact_secrets
from app.gateways.base import (
    ProviderGateway,
    ProviderRejected,
    ProviderUnavailable,
    SubmissionUnknown,
)
from app.repositories.jobs import JobRepository
from app.repositories.ledger import LedgerRepository
from app.services.asset_service import normalize_photo_bytes
from app.services.credential_vault import CredentialVaultService
from app.settings import Settings, get_settings
from app.workers.download import MAX_IMAGE_DOWNLOAD_BYTES, fetch_bounded_url_bytes


async def _ensure_provider_file_path(
    asset_id: str,
    account_fingerprint: str,
    raw_key: str,
    gateway: ProviderGateway,
    settings: Settings,
) -> str:
    now = datetime.now(timezone.utc)
    with get_db_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM assets WHERE id = %s", (asset_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Source asset {asset_id} not found")
            asset = dict(row)

    paths_map = asset.get("provider_file_paths_json") or {}
    if isinstance(paths_map, str):
        try:
            paths_map = json.loads(paths_map)
        except Exception:
            paths_map = {}

    cached = paths_map.get(account_fingerprint)
    if isinstance(cached, dict) and isinstance(cached.get("file_path"), str) and cached.get("expires_at"):
        try:
            exp_dt = datetime.fromisoformat(str(cached["expires_at"]).replace("Z", "+00:00"))
            if exp_dt > now:
                return str(cached["file_path"])
        except Exception:
            pass

    local_path = settings.storage_path / asset["storage_key"]
    file_bytes = local_path.read_bytes()
    reservation = await gateway.reserve_and_upload(
        key=raw_key,
        media_type="image",
        extension="jpg",
        file_bytes=file_bytes,
    )
    paths_map[account_fingerprint] = {
        "file_path": reservation.file_path,
        "expires_at": reservation.expires_at,
    }
    with get_db_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE assets SET provider_file_paths_json = %s WHERE id = %s",
                (json.dumps(paths_map), asset_id),
            )
    return reservation.file_path


async def _prepare_renovated_video_frame(
    job: dict[str, Any],
    raw_user_prompt: str,
    input_file_path: str,
    account_fingerprint: str,
    raw_key: str,
    gateway: ProviderGateway,
    settings: Settings,
) -> str:
    # 1. If a generated_image already exists for this exact brief_revision_id, reuse it directly
    with get_db_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT output_asset_id
                FROM generations
                WHERE brief_revision_id = %s AND kind = 'image' AND output_asset_id IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (job["brief_revision_id"],),
            )
            existing = cur.fetchone()
            if existing and existing.get("output_asset_id"):
                return await _ensure_provider_file_path(
                    asset_id=str(existing["output_asset_id"]),
                    account_fingerprint=account_fingerprint,
                    raw_key=raw_key,
                    gateway=gateway,
                    settings=settings,
                )

    # 2. Only run Magic Hour pre-frame image edit when using an active key on api.magichour.ai
    if not raw_key or getattr(gateway, "base", "") != "https://api.magichour.ai/v1":
        return input_file_path

    try:
        frame_creation = await gateway.create_image(
            key=raw_key,
            name=f"{job['correlation_name']}:frame"[:120],
            model="qwen-edit",
            resolution="1k",
            prompt=raw_user_prompt,
            image_file_paths=[input_file_path],
            image_count=1,
        )
        download_url: str | None = None
        for _ in range(45):
            await asyncio.sleep(1.5)
            st = await gateway.get_project_status(
                key=raw_key,
                kind="image",
                provider_id=frame_creation.provider_id,
            )
            if st.status == "complete" and st.downloads:
                download_url = st.downloads[0].url
                break
            if st.status in {"error", "canceled"}:
                break

        if not download_url:
            return input_file_path

        raw_bytes = await fetch_bounded_url_bytes(
            download_url,
            max_bytes=MAX_IMAGE_DOWNLOAD_BYTES,
            settings=settings,
        )
        norm = normalize_photo_bytes(raw_bytes, filename="frame.jpg", settings=settings)
        asset_id = f"ast_{secrets.token_hex(8)}"
        token = secrets.token_hex(16)
        owner_prefix = str(job["owner_id_hash"])[:12]
        storage_key = f"private/assets/{owner_prefix}/{token}.jpg"
        thumb_key = f"private/thumbs/{owner_prefix}/{token}_thumb.jpg"

        full_path = settings.storage_path / storage_key
        thumb_path = settings.storage_path / thumb_key
        full_path.parent.mkdir(parents=True, exist_ok=True)
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(norm["normalized_bytes"])
        thumb_path.write_bytes(norm["thumb_bytes"])

        now = datetime.now(timezone.utc)
        norm_meta = {
            "thumbnail_key": thumb_key,
            "provider_id": frame_creation.provider_id,
            "job_id": job["id"],
        }
        with get_db_conn(settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO assets (
                        id, owner_id_hash, project_id, room_id, role, storage_key,
                        sha256, mime_type, bytes_size, source_width, source_height,
                        width, height, normalization_transform_json, created_at
                    )
                    VALUES (%s, %s, %s, %s, 'generated_image', %s, %s, 'image/jpeg', %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        asset_id,
                        job["owner_id_hash"],
                        job["project_id"],
                        job["room_id"],
                        storage_key,
                        norm["sha256"],
                        norm["bytes_size"],
                        norm["width"],
                        norm["height"],
                        norm["width"],
                        norm["height"],
                        json.dumps(norm_meta),
                        now,
                    ),
                )
                cur.execute(
                    "UPDATE brief_revisions SET accepted_reference_asset_id = %s WHERE id = %s",
                    (asset_id, job["brief_revision_id"]),
                )
                cur.execute(
                    "UPDATE generations SET source_asset_id = %s WHERE id = %s",
                    (asset_id, job["id"]),
                )

        return await _ensure_provider_file_path(
            asset_id=asset_id,
            account_fingerprint=account_fingerprint,
            raw_key=raw_key,
            gateway=gateway,
            settings=settings,
        )
    except Exception:
        return input_file_path


async def submit_job(
    job_id: str,
    settings: Settings | None = None,
    gateway: ProviderGateway | None = None,
    crash_point: str | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    gw = gateway or get_gateway(cfg)
    job_repo = JobRepository(cfg)
    ledger = LedgerRepository(cfg)
    vault = CredentialVaultService(cfg)

    with get_db_conn(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT g.*, q.estimated_credits, b.accepted_reference_asset_id, b.raw_text
                FROM generations g
                JOIN quotes q ON q.id = g.quote_id
                JOIN brief_revisions b ON b.id = g.brief_revision_id
                WHERE g.id = %s
                """,
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Job {job_id} not found")
            job = dict(row)

    estimated_credits = int(job.get("estimated_credits") or 0)
    accepted_ref_asset_id = job.get("accepted_reference_asset_id")
    raw_user_prompt = str(job.get("raw_text") or "").strip() or str(job["compiled_prompt"])

    # 1. If provider_id is already recorded, never submit again
    if job.get("provider_id"):
        if job["state"] in {"admitted", "preparing", "submitting", "submission_unknown"}:
            return job_repo.transition_job(
                job_id=job_id,
                next_state="queued",
                safe_message="Provider project ID already recorded; advancing to polling.",
                next_poll_at=datetime.now(timezone.utc),
                clear_lease=True,
            )
        return job

    # 2. If job was left in 'submitting' (e.g. crash after paid POST before provider_id was saved),
    # transition to 'submission_unknown' and DO NOT replay the paid request!
    if job["state"] == "submitting":
        now = datetime.now(timezone.utc)
        with get_db_conn(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE provider_attempts
                    SET state = 'submission_unknown', error_code = 'lease_expired_during_submit', completed_at = %s
                    WHERE job_id = %s AND state = 'submitting'
                    """,
                    (now, job_id),
                )
        return job_repo.transition_job(
            job_id=job_id,
            next_state="submission_unknown",
            safe_message=(
                f"Worker interrupted during paid submission (correlation '{job['correlation_name']}'). "
                "Automatic replay is blocked to prevent duplicate charges."
            ),
            last_safe_error={
                "code": "submission_unknown",
                "message": "Submission outcome is ambiguous; verify in Magic Hour dashboard before retrying.",
                "retryable": False,
            },
            clear_lease=True,
        )

    # 3. Advance admitted -> preparing
    if job["state"] == "admitted":
        job = job_repo.transition_job(
            job_id=job_id,
            next_state="preparing",
            safe_message="Preparing normalized room photo and provider upload.",
        )

    # 4. Resolve connected key
    try:
        raw_key, ref = vault.resolve_key_for_owner(job["owner_id_hash"])
    except AppError as exc:
        if exc.code in {"not_connected", "invalid_key"}:
            return job_repo.transition_job(
                job_id=job_id,
                next_state="waiting_for_key",
                safe_message="Magic Hour key expired or disconnected before submission; reconnect to continue.",
                clear_lease=True,
            )
        raise

    account_fp = str(ref["provider_account_fingerprint"])
    if int(ref["balance"]) < estimated_credits:
        return job_repo.transition_job(
            job_id=job_id,
            next_state="blocked_credits",
            safe_message="Insufficient Magic Hour credits before provider submission.",
            clear_lease=True,
        )

    # 5. Reserve and upload source asset(s) to Magic Hour storage for this account_fingerprint
    try:
        primary_file_path = await _ensure_provider_file_path(
            asset_id=job["source_asset_id"],
            account_fingerprint=account_fp,
            raw_key=raw_key,
            gateway=gw,
            settings=cfg,
        )
        image_file_paths = [primary_file_path]
        if accepted_ref_asset_id and accepted_ref_asset_id != job["source_asset_id"]:
            is_ref_image = False
            with get_db_conn(cfg) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT role FROM assets WHERE id = %s", (accepted_ref_asset_id,))
                    ref_row = cur.fetchone()
                    if ref_row and ref_row["role"] in {"original_photo", "generated_image"}:
                        is_ref_image = True
            if is_ref_image:
                ref_path = await _ensure_provider_file_path(
                    asset_id=accepted_ref_asset_id,
                    account_fingerprint=account_fp,
                    raw_key=raw_key,
                    gateway=gw,
                    settings=cfg,
                )
                primary_file_path = ref_path
                image_file_paths = [ref_path]
        if job["kind"] == "video":
            primary_file_path = await _prepare_renovated_video_frame(
                job=job,
                raw_user_prompt=raw_user_prompt,
                input_file_path=primary_file_path,
                account_fingerprint=account_fp,
                raw_key=raw_key,
                gateway=gw,
                settings=cfg,
            )
            image_file_paths = [primary_file_path]
    except ProviderRejected as exc:
        if exc.status == 401:
            return job_repo.transition_job(
                job_id=job_id,
                next_state="waiting_for_key",
                safe_message="Provider rejected API key during asset upload; reconnect a valid key.",
                clear_lease=True,
            )
        return job_repo.transition_job(
            job_id=job_id,
            next_state="failed",
            safe_message="Provider rejected source image upload.",
            last_safe_error={"code": exc.code, "message": redact_secrets(exc.message), "retryable": False},
            clear_lease=True,
        )
    except ProviderUnavailable as exc:
        return job_repo.transition_job(
            job_id=job_id,
            next_state="failed",
            safe_message="Provider storage was temporarily unavailable during upload.",
            last_safe_error={"code": "provider_unavailable", "message": redact_secrets(exc.reason), "retryable": True},
            clear_lease=True,
        )

    if crash_point == "before_submit":
        raise RuntimeError("Simulated crash before provider submit")

    # 6. Persist provider_attempts row and transition job to 'submitting' BEFORE the paid POST
    opts = json.loads(job["options_json"]) if isinstance(job["options_json"], str) else (job["options_json"] or {})
    resolution = str(opts.get("resolution", "1k"))
    image_count = int(opts.get("image_count", 1))
    duration_seconds = int(opts.get("duration_seconds") or 5)
    audio = bool(opts.get("audio", False))

    attempt_id = f"att_{secrets.token_hex(8)}"
    now = datetime.now(timezone.utc)
    req_summary = {
        "kind": job["kind"],
        "name": job["correlation_name"],
        "model": job["model"],
        "resolution": resolution,
        "prompt": raw_user_prompt,
        "image_file_paths": image_file_paths if job["kind"] == "image" else [primary_file_path],
    }

    with get_db_conn(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO provider_attempts (
                    id, job_id, state, account_fingerprint, request_payload_json, created_at
                )
                VALUES (%s, %s, 'submitting', %s, %s, %s)
                """,
                (attempt_id, job_id, account_fp, json.dumps(req_summary), now),
            )
            ledger.record_event(
                owner_id_hash=job["owner_id_hash"],
                account_fingerprint=account_fp,
                job_id=job_id,
                attempt_id=attempt_id,
                quote_id=job["quote_id"],
                event_type="submission_started",
                estimated_amount=estimated_credits,
                source="submit_worker",
                cur=cur,
            )

    job_repo.transition_job(
        job_id=job_id,
        next_state="submitting",
        safe_message="Submitting generation request to Magic Hour.",
        safe_payload={"attempt_id": attempt_id, "correlation_name": job["correlation_name"]},
    )

    # 7. Execute paid creation call (NEVER automatically retried inside gateway)
    try:
        if job["kind"] == "image":
            creation = await gw.create_image(
                key=raw_key,
                name=job["correlation_name"],
                model=job["model"],
                resolution=resolution,
                prompt=raw_user_prompt,
                image_file_paths=image_file_paths,
                image_count=image_count,
            )
        else:
            # Optimize video prompt to focus on steady camera push, architectural preservation, and no unwanted people/distortions
            optimized_video_prompt = (
                f"{raw_user_prompt.strip()} "
                "Empty room with no people, steady smooth camera walkthrough, realistic interior architectural lines, "
                "consistent materials and lighting throughout, high quality."
            ).strip()
            creation = await gw.create_video(
                key=raw_key,
                name=job["correlation_name"],
                model=job["model"],
                resolution=resolution,
                end_seconds=duration_seconds,
                prompt=optimized_video_prompt,
                image_file_path=primary_file_path,
                audio=audio,
            )

        if crash_point == "after_submit_before_persist":
            raise RuntimeError("Simulated crash after provider submit before persisting provider_id")

        done_now = datetime.now(timezone.utc)
        with get_db_conn(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE provider_attempts
                    SET state = 'submitted',
                        provider_id = %s,
                        response_status = 200,
                        observed_credits = %s,
                        completed_at = %s
                    WHERE id = %s
                    """,
                    (creation.provider_id, creation.credits_charged, done_now, attempt_id),
                )
                if creation.credits_charged is not None:
                    ledger.record_event(
                        owner_id_hash=job["owner_id_hash"],
                        account_fingerprint=account_fp,
                        job_id=job_id,
                        attempt_id=attempt_id,
                        quote_id=job["quote_id"],
                        event_type="provider_charge_observed",
                        estimated_amount=estimated_credits,
                        observed_amount=creation.credits_charged,
                        source="submit_worker",
                        cur=cur,
                    )
                    cur.execute(
                        """
                        UPDATE credential_references
                        SET balance = GREATEST(0, balance - %s), balance_checked_at = %s
                        WHERE id = %s
                        """,
                        (creation.credits_charged, done_now, ref["id"]),
                    )

        return job_repo.transition_job(
            job_id=job_id,
            next_state="queued",
            provider_state="queued",
            provider_id=creation.provider_id,
            observed_credits_charged=creation.credits_charged,
            next_poll_at=done_now,
            safe_message="Provider accepted generation request; job is queued.",
            safe_payload={
                "provider_id": creation.provider_id,
                "observed_credits_charged": creation.credits_charged,
            },
            clear_lease=True,
        )

    except ProviderRejected as exc:
        done_now = datetime.now(timezone.utc)
        with get_db_conn(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE provider_attempts
                    SET state = 'rejected',
                        response_status = %s,
                        observed_credits = 0,
                        error_code = %s,
                        completed_at = %s
                    WHERE id = %s
                    """,
                    (exc.status, exc.code, done_now, attempt_id),
                )
                ledger.record_event(
                    owner_id_hash=job["owner_id_hash"],
                    account_fingerprint=account_fp,
                    job_id=job_id,
                    attempt_id=attempt_id,
                    quote_id=job["quote_id"],
                    event_type="submission_rejected",
                    estimated_amount=estimated_credits,
                    observed_amount=0,
                    source="submit_worker",
                    cur=cur,
                )

        if exc.status == 402 or exc.code == "insufficient_credits":
            return job_repo.transition_job(
                job_id=job_id,
                next_state="blocked_credits",
                safe_message="Magic Hour rejected submission due to insufficient credits (402). Top up and refresh balance.",
                last_safe_error={"code": "insufficient_credits", "message": redact_secrets(exc.message), "retryable": True},
                clear_lease=True,
            )
        if exc.status == 401:
            return job_repo.transition_job(
                job_id=job_id,
                next_state="waiting_for_key",
                safe_message="Magic Hour rejected the API key (401). Reconnect a valid key.",
                last_safe_error={"code": "invalid_key", "message": redact_secrets(exc.message), "retryable": True},
                clear_lease=True,
            )
        return job_repo.transition_job(
            job_id=job_id,
            next_state="failed",
            safe_message=f"Magic Hour rejected generation request ({exc.code}).",
            last_safe_error={"code": exc.code, "message": redact_secrets(exc.message), "retryable": False},
            clear_lease=True,
        )

    except SubmissionUnknown as exc:
        done_now = datetime.now(timezone.utc)
        with get_db_conn(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE provider_attempts
                    SET state = 'submission_unknown',
                        error_code = 'submission_unknown',
                        completed_at = %s
                    WHERE id = %s
                    """,
                    (done_now, attempt_id),
                )
        return job_repo.transition_job(
            job_id=job_id,
            next_state="submission_unknown",
            safe_message=(
                f"Provider returned an ambiguous response for '{job['correlation_name']}'. "
                "Automatic retry is blocked to prevent duplicate credit charges."
            ),
            last_safe_error={
                "code": "submission_unknown",
                "message": redact_secrets(exc.reason),
                "retryable": False,
            },
            clear_lease=True,
        )
