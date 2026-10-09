from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from fastapi import APIRouter, Depends, Query

from app.dependencies import SessionOwner, require_csrf, require_owner
from app.domain.schemas import (
    CreateProjectRequest,
    ProjectListResponse,
    ProjectSummary,
    RoomSummary,
)
from app.repositories.projects import ProjectRepository
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _format_room(rm: dict[str, Any], owner_id_hash: str, settings: Settings) -> RoomSummary:
    from app.services.asset_service import sign_asset_url

    primary_id = rm.get("primary_asset_id")
    accepted_img_id = rm.get("accepted_image_asset_id")
    accepted_clip_id = rm.get("accepted_clip_asset_id")
    return RoomSummary(
        id=rm["id"],
        project_id=rm["project_id"],
        name=rm["name"],
        room_type=rm["room_type"],
        sort_order=int(rm.get("sort_order", 0)),
        primary_asset_id=primary_id,
        thumbnail_url=sign_asset_url(primary_id, owner_id_hash, settings, variant="thumb") if primary_id else None,
        active_brief_revision_id=rm.get("active_brief_revision_id"),
        accepted_image_asset_id=accepted_img_id,
        accepted_image_url=sign_asset_url(accepted_img_id, owner_id_hash, settings) if accepted_img_id else None,
        accepted_image_review_id=rm.get("accepted_image_review_id"),
        accepted_clip_asset_id=accepted_clip_id,
        accepted_clip_url=sign_asset_url(accepted_clip_id, owner_id_hash, settings) if accepted_clip_id else None,
        accepted_clip_review_id=rm.get("accepted_clip_review_id"),
        latest_job_id=rm.get("latest_job_id"),
    )


def _format_project(proj: dict[str, Any], owner_id_hash: str, settings: Settings) -> ProjectSummary:
    created_at = proj["created_at"]
    if isinstance(created_at, datetime):
        expires_dt = created_at + timedelta(days=settings.ANONYMOUS_RETENTION_DAYS)
        created_str = created_at.isoformat()
        expires_str = expires_dt.isoformat()
    else:
        created_str = str(created_at)
        expires_str = (datetime.now(timezone.utc) + timedelta(days=settings.ANONYMOUS_RETENTION_DAYS)).isoformat()

    rooms = [_format_room(r, owner_id_hash, settings) for r in proj.get("rooms", [])]
    return ProjectSummary(
        id=proj["id"],
        name=proj["name"],
        is_mock_seed=bool(proj.get("is_mock_seed", False)),
        room_count=len(rooms),
        created_at=created_str,
        expires_at=expires_str,
        rooms=rooms,
    )


@router.post("", response_model=ProjectSummary, status_code=201)
def create_project(
    body: CreateProjectRequest,
    owner: SessionOwner = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
) -> ProjectSummary:
    repo = ProjectRepository(settings)
    proj = repo.create_project(owner_id_hash=owner.id_hash, name=body.name)
    return _format_project(proj, owner.id_hash, settings)


@router.get("", response_model=ProjectListResponse)
def list_projects(
    cursor: str | None = Query(default=None),
    owner: SessionOwner = Depends(require_owner),
    settings: Settings = Depends(get_settings),
) -> ProjectListResponse:
    repo = ProjectRepository(settings)
    rows = repo.list_projects(owner_id_hash=owner.id_hash, cursor=cursor)
    items = [_format_project(p, owner.id_hash, settings) for p in rows]
    return ProjectListResponse(items=items, next_cursor=None)


@router.get("/{project_id}", response_model=ProjectSummary)
def get_project(
    project_id: str,
    owner: SessionOwner = Depends(require_owner),
    settings: Settings = Depends(get_settings),
) -> ProjectSummary:
    repo = ProjectRepository(settings)
    proj = repo.get_project(owner_id_hash=owner.id_hash, project_id=project_id)
    return _format_project(proj, owner.id_hash, settings)


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    owner: SessionOwner = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    from app.services.retention_service import RetentionService

    repo = ProjectRepository(settings)
    tombstoned = repo.tombstone_project(owner_id_hash=owner.id_hash, project_id=project_id)
    cleanup_stats = RetentionService(settings).cleanup_tombstoned_projects()
    return {
        "id": tombstoned["id"],
        "status": "tombstoned",
        "cleanup_status": "cleaned" if cleanup_stats["cleaned_projects"] > 0 else tombstoned["cleanup_status"],
        "deleted_at": tombstoned["deleted_at"].isoformat() if tombstoned.get("deleted_at") else None,
        "provider_retention_notice": (
            "Project removed from magicrenovator and local private assets scheduled for deletion. "
            "Media previously generated in your Magic Hour account remains governed by Magic Hour's library retention."
        ),
    }

