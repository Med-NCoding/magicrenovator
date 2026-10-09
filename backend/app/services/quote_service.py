from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.dependencies import get_db_conn
from app.domain.errors import AppError
from app.domain.schemas import CreateQuoteRequest, QuoteResponse
from app.repositories.ledger import LedgerRepository
from app.services.compiler import BriefService, compile_video_prompt
from app.services.credential_vault import CredentialVaultService
from app.settings import Settings, get_settings

QUOTE_TTL_SECONDS = 3600


def compute_quote_spec_hash(
    brief_revision_id: str,
    brief_source_hash: str,
    source_asset_id: str,
    kind: str,
    model: str,
    resolution: str,
    image_count: int,
    duration_seconds: int | None,
    audio: bool,
    motion_preset: str | None,
    catalog_version: str,
) -> str:
    canonical = {
        "brief_revision_id": brief_revision_id,
        "brief_source_hash": brief_source_hash,
        "source_asset_id": source_asset_id,
        "kind": kind,
        "model": model,
        "resolution": resolution,
        "image_count": image_count,
        "duration_seconds": duration_seconds,
        "audio": audio,
        "motion_preset": motion_preset or "",
        "catalog_version": catalog_version,
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class QuoteService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.brief_service = BriefService(self.settings)
        self.vault = CredentialVaultService(self.settings)
        self.ledger = LedgerRepository(self.settings)

    def load_catalog(self) -> dict[str, Any]:
        path = self.settings.resolved_catalog_path()
        return json.loads(path.read_text(encoding="utf-8"))

    def create_quote(self, owner_id_hash: str, body: CreateQuoteRequest) -> QuoteResponse:
        # 1. Verify active Magic Hour credential and get current tier + balance
        ref = self.vault.get_active_reference(owner_id_hash)
        if not ref or ref.get("tier") is None or ref.get("balance") is None:
            raise AppError(
                code="not_connected",
                message="Connect a valid Magic Hour API key before requesting a credit quote.",
                status_code=401,
                retryable=True,
                next_action="connect_key",
            )
        tier = str(ref["tier"])
        balance = int(ref["balance"])
        checked_at_val = ref.get("balance_checked_at") or datetime.now(timezone.utc)
        checked_at_dt = (
            checked_at_val
            if isinstance(checked_at_val, datetime)
            else datetime.fromisoformat(str(checked_at_val))
        )

        # 2. Load brief revision and room ownership
        brief_row, brief, _ = self.brief_service.get_brief_owned(owner_id_hash, body.brief_id)

        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM rooms WHERE id = %s", (brief_row["room_id"],))
                room = dict(cur.fetchone())

        if room.get("active_brief_revision_id") and room["active_brief_revision_id"] != brief_row["id"]:
            # Automatically quote the room's latest active brief revision so revision re-quoting seamlessly uses the newest revision
            brief_row, brief, _ = self.brief_service.get_brief_owned(owner_id_hash, room["active_brief_revision_id"])

        if brief_row.get("has_unresolved_conflicts") or len(brief.unresolved) > 0:
            raise AppError(
                code="invalid_brief",
                message="Resolve all renovation brief conflicts before requesting a quote.",
                status_code=400,
                retryable=False,
                next_action="resolve_conflicts",
            )

        catalog = self.load_catalog()
        catalog_version = catalog["catalog_version"]
        models_by_id = {m["id"]: m for m in catalog["models"]}

        kind = body.kind
        opts = body.options

        if kind == "image":
            source_asset_id = room.get("primary_asset_id") or brief_row.get("source_asset_id")
            if not source_asset_id:
                raise AppError(
                    code="invalid_image",
                    message="Upload a room reference photo before requesting an image quote.",
                    status_code=400,
                    retryable=False,
                    next_action="upload_photo",
                )
            source_review_id = None

            if body.model:
                model_id = body.model
            elif opts.quality_label == "Draft" or tier == "free":
                model_id = "qwen-edit"
            else:
                model_id = "seedream-v4.5"

            model_cfg = models_by_id.get(model_id)
            if not model_cfg or model_cfg["media_kind"] != "image":
                raise AppError(
                    code="unsupported_option",
                    message=f"Unsupported image model '{model_id}'.",
                    status_code=400,
                    retryable=False,
                    next_action="select_valid_model",
                )

            if tier not in model_cfg["allowed_tiers"]:
                raise AppError(
                    code="unsupported_option",
                    message=(
                        f"Model '{model_id}' requires Magic Hour '{model_cfg['minimum_tier']}' tier or higher "
                        f"(current tier: '{tier}'). Choose Draft ('qwen-edit') or upgrade your Magic Hour account."
                    ),
                    status_code=400,
                    retryable=False,
                    next_action="select_draft_or_upgrade",
                )

            resolution = opts.resolution or "1k"
            if resolution not in model_cfg["allowed_resolutions"]:
                raise AppError(
                    code="unsupported_option",
                    message=f"Resolution '{resolution}' is not supported by model '{model_id}'.",
                    status_code=400,
                    retryable=False,
                    next_action="select_valid_resolution",
                )
            if tier == "free" and resolution not in model_cfg.get("free_tier_resolutions", []):
                raise AppError(
                    code="unsupported_option",
                    message=f"Resolution '{resolution}' requires a paid Magic Hour tier for '{model_id}'.",
                    status_code=400,
                    retryable=False,
                    next_action="select_valid_resolution",
                )

            image_count = opts.image_count
            if image_count not in model_cfg.get("allowed_image_counts", [1]):
                raise AppError(
                    code="unsupported_option",
                    message=f"Image count {image_count} is not supported for '{model_id}'.",
                    status_code=400,
                    retryable=False,
                    next_action="select_valid_options",
                )

            unit_cost = int(model_cfg["credit_formula"]["costs_by_resolution"][resolution])
            estimated_credits = unit_cost * image_count
            duration_seconds = None
            audio = False
            motion_preset = None
            motion_prompt = None

            if opts.anticipate_video:
                # Estimate a standard 5s video clip for planning total room workflow spend
                anticipated_clip_credits = 120 if tier == "free" else 240
                anticipated_total = estimated_credits + anticipated_clip_credits
            else:
                anticipated_clip_credits = None
                anticipated_total = estimated_credits

        else:
            # kind == "video": Use accepted still image if available, or direct room photo if allow_direct_video is enabled
            accepted_asset_id = room.get("accepted_image_asset_id")
            accepted_review_id = room.get("accepted_image_review_id")
            if accepted_asset_id and accepted_review_id:
                with get_db_conn(self.settings) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT id, decision FROM reviews WHERE id = %s AND asset_id = %s AND owner_id_hash = %s",
                            (accepted_review_id, accepted_asset_id, owner_id_hash),
                        )
                        rev_row = cur.fetchone()
                        if not rev_row or rev_row["decision"] != "accept":
                            raise AppError(
                                code="invalid_brief",
                                message="Video clip generation requires an accepted still image review.",
                                status_code=400,
                                retryable=False,
                                next_action="accept_still_image",
                            )
                source_asset_id = accepted_asset_id
                source_review_id = accepted_review_id
            elif opts.allow_direct_video:
                source_asset_id = (
                    brief_row.get("accepted_reference_asset_id")
                    or room.get("primary_asset_id")
                    or brief_row.get("source_asset_id")
                )
                if not source_asset_id:
                    raise AppError(
                        code="invalid_image",
                        message="Upload a room reference photo before requesting a video quote.",
                        status_code=400,
                        retryable=False,
                        next_action="upload_photo",
                    )
                source_review_id = None
            else:
                raise AppError(
                    code="invalid_brief",
                    message="You must review and accept a renovated still image before quoting a room video clip.",
                    status_code=400,
                    retryable=False,
                    next_action="accept_still_image",
                )

            if body.model:
                model_id = body.model
            elif opts.quality_label == "Draft" or tier == "free":
                model_id = "ltx-2.5"
            else:
                model_id = "kling-3.0"

            model_cfg = models_by_id.get(model_id)
            if not model_cfg or model_cfg["media_kind"] != "video":
                raise AppError(
                    code="unsupported_option",
                    message=f"Unsupported video model '{model_id}'.",
                    status_code=400,
                    retryable=False,
                    next_action="select_valid_model",
                )

            if tier not in model_cfg["allowed_tiers"]:
                raise AppError(
                    code="unsupported_option",
                    message=(
                        f"Video model '{model_id}' requires Magic Hour '{model_cfg['minimum_tier']}' tier or higher "
                        f"(current tier: '{tier}'). Choose Draft ('ltx-2.5') or upgrade your Magic Hour account."
                    ),
                    status_code=400,
                    retryable=False,
                    next_action="select_draft_or_upgrade",
                )

            default_vid_res = "480p" if tier == "free" else "720p"
            resolution = opts.resolution if opts.resolution in ("360p", "480p", "720p", "1080p", "4k") else default_vid_res
            if resolution not in model_cfg["allowed_resolutions"]:
                raise AppError(
                    code="unsupported_option",
                    message=f"Resolution '{resolution}' is not supported by video model '{model_id}'.",
                    status_code=400,
                    retryable=False,
                    next_action="select_valid_resolution",
                )
            if tier == "free" and resolution not in model_cfg.get("free_tier_resolutions", []):
                raise AppError(
                    code="unsupported_option",
                    message=f"Resolution '{resolution}' requires a paid Magic Hour tier for '{model_id}'.",
                    status_code=400,
                    retryable=False,
                    next_action="select_valid_resolution",
                )

            duration_seconds = opts.duration_seconds
            if duration_seconds not in model_cfg.get("allowed_durations", [5]):
                raise AppError(
                    code="unsupported_option",
                    message=f"Duration {duration_seconds}s is not supported by video model '{model_id}'.",
                    status_code=400,
                    retryable=False,
                    next_action="select_valid_duration",
                )

            audio = bool(opts.audio)
            if audio and not model_cfg.get("supports_audio", False):
                raise AppError(
                    code="unsupported_option",
                    message=f"Audio is not supported by video model '{model_id}'.",
                    status_code=400,
                    retryable=False,
                    next_action="disable_audio",
                )

            per_sec = int(model_cfg["credit_formula"]["credits_per_second"][resolution])
            audio_extra = int(model_cfg.get("audio_extra_credits_per_second", {}).get(resolution, 0)) if audio else 0
            estimated_credits = (per_sec + audio_extra) * duration_seconds
            image_count = 1
            motion_preset = opts.motion_preset or "gentle_push"
            motion_prompt = compile_video_prompt(brief, motion_preset=motion_preset)
            anticipated_clip_credits = None
            anticipated_total = estimated_credits

        if estimated_credits > self.settings.MAX_WORKFLOW_CREDITS:
            raise AppError(
                code="unsupported_option",
                message=f"Estimated cost ({estimated_credits} credits) exceeds the workflow safety cap ({self.settings.MAX_WORKFLOW_CREDITS} credits).",
                status_code=400,
                retryable=False,
                next_action="lower_resolution_or_duration",
            )

        spec_hash = compute_quote_spec_hash(
            brief_revision_id=brief_row["id"],
            brief_source_hash=brief_row["source_hash"],
            source_asset_id=source_asset_id,
            kind=kind,
            model=model_id,
            resolution=resolution,
            image_count=image_count,
            duration_seconds=duration_seconds,
            audio=audio,
            motion_preset=motion_preset,
            catalog_version=catalog_version,
        )

        quote_id = f"qte_{secrets.token_hex(8)}"
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=QUOTE_TTL_SECONDS)

        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO quotes (
                        id, owner_id_hash, project_id, room_id, brief_revision_id,
                        source_asset_id, source_review_id, kind, model, resolution,
                        image_count, duration_seconds, audio, motion_preset, motion_prompt,
                        spec_hash, estimated_credits, authorized_max_credits, anticipated_clip_credits,
                        balance_snapshot, balance_checked_at, catalog_version,
                        requires_confirmation, created_at, expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s)
                    """,
                    (
                        quote_id,
                        owner_id_hash,
                        room["project_id"],
                        room["id"],
                        brief_row["id"],
                        source_asset_id,
                        source_review_id,
                        kind,
                        model_id,
                        resolution,
                        image_count,
                        duration_seconds,
                        audio,
                        motion_preset,
                        motion_prompt,
                        spec_hash,
                        estimated_credits,
                        estimated_credits,
                        anticipated_clip_credits,
                        balance,
                        checked_at_dt,
                        catalog_version,
                        now,
                        expires_at,
                    ),
                )
                self.ledger.record_event(
                    owner_id_hash=owner_id_hash,
                    event_type="quote_created",
                    source="quote_service",
                    quote_id=quote_id,
                    estimated_amount=estimated_credits,
                    cur=cur,
                )

        return QuoteResponse(
            quote_id=quote_id,
            kind=kind,
            brief_revision_id=brief_row["id"],
            source_asset_id=source_asset_id,
            model=model_id,
            quality_label=model_cfg["label"],
            resolution=resolution,
            image_count=image_count,
            duration_seconds=duration_seconds,
            audio=audio,
            motion_preset=motion_preset,
            estimated_credits=estimated_credits,
            authorized_max_credits=estimated_credits,
            anticipated_clip_credits=anticipated_clip_credits,
            anticipated_total_workflow_credits=anticipated_total,
            balance=balance,
            balance_checked_at=checked_at_dt.isoformat(),
            sufficient_credits=(balance >= estimated_credits),
            catalog_version=catalog_version,
            expires_at=expires_at.isoformat(),
            requires_confirmation=True,
        )
