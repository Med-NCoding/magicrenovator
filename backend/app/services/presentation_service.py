from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.dependencies import get_db_conn
from app.domain.errors import AppError
from app.domain.schemas import (
    CreatePresentationRequest,
    ExportMediaItem,
    ExportResponse,
    PresentationClipItem,
    PresentationJobResponse,
)
from app.repositories.projects import ProjectRepository
from app.services.asset_service import sign_asset_url
from app.settings import Settings, get_settings
from app.workers.assemble import CONCEPT_LIMITATION_NOTICE

ASSEMBLER_VERSION = "presentation-v1"
OUTPUT_PROFILE = {
    "width": 1280,
    "height": 720,
    "fps": 30,
    "video_codec": "libx264",
    "pix_fmt": "yuv420p",
}


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return s or "room"


class PresentationService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.project_repo = ProjectRepository(self.settings)

    def create_presentation(
        self,
        owner_id_hash: str,
        project_id: str,
        body: CreatePresentationRequest,
    ) -> PresentationJobResponse:
        proj = self.project_repo.get_project(owner_id_hash=owner_id_hash, project_id=project_id)
        rooms = proj.get("rooms") or []

        requested_clips = list(body.ordered_clips)
        if not requested_clips:
            for rm in rooms:
                if rm.get("accepted_clip_asset_id"):
                    requested_clips.append(
                        PresentationClipItem(
                            asset_id=rm["accepted_clip_asset_id"],
                            room_label=rm["name"][:60],
                        )
                    )

        if not requested_clips:
            raise AppError(
                code="validation_error",
                message="At least one accepted room video clip is required to assemble a house presentation.",
                status_code=400,
                retryable=False,
                next_action="accept_room_clip",
            )
        if len(requested_clips) > self.settings.MAX_ROOMS_PER_PROJECT:
            raise AppError(
                code="validation_error",
                message=f"Presentations support up to {self.settings.MAX_ROOMS_PER_PROJECT} room clips.",
                status_code=400,
                retryable=False,
                next_action="reduce_clips",
            )

        clip_specs: list[dict[str, Any]] = []
        hash_clip_entries: list[dict[str, str]] = []

        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                for item in requested_clips:
                    cur.execute(
                        """
                        SELECT a.*, r.accepted_clip_asset_id
                        FROM assets a
                        LEFT JOIN rooms r ON r.id = a.room_id
                        WHERE a.id = %s AND a.project_id = %s AND a.owner_id_hash = %s
                          AND a.deleted_at IS NULL
                        """,
                        (item.asset_id, project_id, owner_id_hash),
                    )
                    asset_row = cur.fetchone()
                    if not asset_row or asset_row["role"] != "generated_video":
                        raise AppError(
                            code="validation_error",
                            message=f"Clip asset '{item.asset_id}' is not a valid room video clip in this project.",
                            status_code=400,
                            retryable=False,
                            next_action="select_valid_clip",
                        )

                    cur.execute(
                        """
                        SELECT id FROM reviews
                        WHERE asset_id = %s AND owner_id_hash = %s AND decision = 'accept'
                        LIMIT 1
                        """,
                        (item.asset_id, owner_id_hash),
                    )
                    accepted_rev = cur.fetchone()
                    if not accepted_rev and asset_row.get("accepted_clip_asset_id") != item.asset_id:
                        raise AppError(
                            code="validation_error",
                            message=f"Clip asset '{item.asset_id}' has not been accepted in human review.",
                            status_code=400,
                            retryable=False,
                            next_action="accept_room_clip",
                        )

                    clean_label = item.room_label.strip()[:60] or "Room"
                    clip_specs.append(
                        {
                            "asset_id": item.asset_id,
                            "room_id": asset_row.get("room_id"),
                            "room_label": clean_label,
                            "storage_key": asset_row["storage_key"],
                            "sha256": asset_row["sha256"],
                        }
                    )
                    hash_clip_entries.append(
                        {
                            "asset_id": item.asset_id,
                            "sha256": asset_row["sha256"],
                            "room_label": clean_label,
                        }
                    )

                # Gather room brief data for Markdown handoff brief
                rooms_brief_data: list[dict[str, Any]] = []
                for rm in rooms:
                    brief_spec: dict[str, Any] = {}
                    if rm.get("active_brief_revision_id"):
                        cur.execute(
                            "SELECT spec_json FROM brief_revisions WHERE id = %s",
                            (rm["active_brief_revision_id"],),
                        )
                        b_row = cur.fetchone()
                        if b_row and b_row.get("spec_json"):
                            brief_spec = (
                                json.loads(b_row["spec_json"])
                                if isinstance(b_row["spec_json"], str)
                                else b_row["spec_json"]
                            )
                    rooms_brief_data.append(
                        {
                            "room_id": rm["id"],
                            "name": rm["name"],
                            "room_type": rm["room_type"],
                            "layout_mode": brief_spec.get("layout_mode", "preserve"),
                            "style": brief_spec.get("style"),
                            "preserve": brief_spec.get("preserve", []),
                            "changes": brief_spec.get("changes", []),
                            "accepted_image_asset_id": rm.get("accepted_image_asset_id"),
                            "accepted_clip_asset_id": rm.get("accepted_clip_asset_id"),
                        }
                    )

                canonical_for_hash = {
                    "project_id": project_id,
                    "title": body.title.strip(),
                    "include_concept_label": bool(body.include_concept_label),
                    "assembler_version": ASSEMBLER_VERSION,
                    "output_profile": OUTPUT_PROFILE,
                    "clips": hash_clip_entries,
                }
                manifest_hash = hashlib.sha256(
                    json.dumps(canonical_for_hash, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()

                # Check idempotent reuse of existing export for identical manifest_hash
                cur.execute(
                    """
                    SELECT * FROM exports
                    WHERE project_id = %s AND owner_id_hash = %s AND manifest_hash = %s
                      AND status IN ('queued', 'rendering', 'ready')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (project_id, owner_id_hash, manifest_hash),
                )
                existing_exp = cur.fetchone()
                if existing_exp:
                    return PresentationJobResponse(
                        export_id=existing_exp["id"],
                        presentation_id=existing_exp["presentation_id"],
                        status=existing_exp["status"],
                        manifest_hash=manifest_hash,
                        status_route=f"/api/exports/{existing_exp['id']}",
                    )

                presentation_id = f"prs_{secrets.token_hex(8)}"
                export_id = f"exp_{secrets.token_hex(8)}"
                outbox_id = f"obx_{secrets.token_hex(8)}"
                now = datetime.now(timezone.utc)

                full_manifest = {
                    **canonical_for_hash,
                    "clips": clip_specs,
                    "rooms_brief_data": rooms_brief_data,
                }

                cur.execute(
                    """
                    INSERT INTO presentations (
                        id, owner_id_hash, project_id, title, ordered_clips_json,
                        manifest_json, manifest_hash, include_concept_label, assembler_version, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        presentation_id,
                        owner_id_hash,
                        project_id,
                        body.title.strip(),
                        json.dumps([c.model_dump() for c in requested_clips]),
                        json.dumps(full_manifest),
                        manifest_hash,
                        bool(body.include_concept_label),
                        ASSEMBLER_VERSION,
                        now,
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO exports (
                        id, owner_id_hash, project_id, presentation_id, manifest_hash,
                        status, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, 'queued', %s, %s)
                    """,
                    (export_id, owner_id_hash, project_id, presentation_id, manifest_hash, now, now),
                )
                cur.execute(
                    """
                    INSERT INTO outbox (id, export_id, event_type, payload_json, dispatched, created_at)
                    VALUES (%s, %s, 'assemble_presentation', %s, FALSE, %s)
                    """,
                    (outbox_id, export_id, json.dumps({"export_id": export_id}), now),
                )

                return PresentationJobResponse(
                    export_id=export_id,
                    presentation_id=presentation_id,
                    status="queued",
                    manifest_hash=manifest_hash,
                    status_route=f"/api/exports/{export_id}",
                )

    def get_export(self, owner_id_hash: str, export_id: str) -> ExportResponse:
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT e.*, p.created_at AS project_created_at
                    FROM exports e
                    JOIN projects p ON p.id = e.project_id
                    WHERE e.id = %s AND e.owner_id_hash = %s AND p.deleted_at IS NULL
                    """,
                    (export_id, owner_id_hash),
                )
                row = cur.fetchone()
                if not row:
                    raise AppError(
                        code="not_found",
                        message="Presentation export not found.",
                        status_code=404,
                        retryable=False,
                        next_action="none",
                    )
                exp = dict(row)

                brief_md_content: str | None = None
                if exp.get("brief_asset_id"):
                    cur.execute(
                        "SELECT storage_key FROM assets WHERE id = %s AND owner_id_hash = %s",
                        (exp["brief_asset_id"], owner_id_hash),
                    )
                    md_asset = cur.fetchone()
                    if md_asset:
                        md_path = self.settings.storage_path / md_asset["storage_key"]
                        if md_path.exists():
                            brief_md_content = md_path.read_text(encoding="utf-8")

                cur.execute(
                    """
                    SELECT * FROM rooms
                    WHERE project_id = %s AND deleted_at IS NULL
                    ORDER BY sort_order ASC, created_at ASC
                    """,
                    (exp["project_id"],),
                )
                rooms = [dict(r) for r in cur.fetchall()]

        room_media: list[ExportMediaItem] = []
        for idx, rm in enumerate(rooms, start=1):
            slug = _slugify(rm["name"])
            if rm.get("accepted_image_asset_id"):
                img_id = rm["accepted_image_asset_id"]
                room_media.append(
                    ExportMediaItem(
                        room_id=rm["id"],
                        room_name=rm["name"],
                        kind="image",
                        asset_id=img_id,
                        filename=f"{idx:02d}_{slug}_concept.jpg",
                        download_url=sign_asset_url(img_id, owner_id_hash, self.settings),
                    )
                )
            if rm.get("accepted_clip_asset_id"):
                clip_id = rm["accepted_clip_asset_id"]
                room_media.append(
                    ExportMediaItem(
                        room_id=rm["id"],
                        room_name=rm["name"],
                        kind="video",
                        asset_id=clip_id,
                        filename=f"{idx:02d}_{slug}_clip.mp4",
                        download_url=sign_asset_url(clip_id, owner_id_hash, self.settings),
                    )
                )

        vid_url = (
            sign_asset_url(exp["video_asset_id"], owner_id_hash, self.settings)
            if exp.get("video_asset_id")
            else None
        )
        md_url = (
            sign_asset_url(exp["brief_asset_id"], owner_id_hash, self.settings)
            if exp.get("brief_asset_id")
            else None
        )
        proj_created = exp["project_created_at"]
        expires_dt = (
            (proj_created if isinstance(proj_created, datetime) else datetime.now(timezone.utc))
            + timedelta(days=self.settings.ANONYMOUS_RETENTION_DAYS)
        )

        return ExportResponse(
            export_id=exp["id"],
            project_id=exp["project_id"],
            presentation_id=exp["presentation_id"],
            status=exp["status"],
            manifest_hash=exp["manifest_hash"],
            presentation_video_url=vid_url,
            brief_markdown_url=md_url,
            brief_markdown=brief_md_content,
            room_media=room_media,
            concept_limitation_notice=CONCEPT_LIMITATION_NOTICE,
            expires_at=expires_dt.isoformat(),
        )
