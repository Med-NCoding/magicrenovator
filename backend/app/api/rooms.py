from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.projects import _format_room
from app.dependencies import SessionOwner, require_csrf, require_owner
from app.domain.schemas import CreateRoomRequest, RoomSummary, UpdateRoomRequest
from app.repositories.projects import ProjectRepository
from app.settings import Settings, get_settings

router = APIRouter(tags=["rooms"])


@router.post("/api/projects/{project_id}/rooms", response_model=RoomSummary, status_code=201)
def create_room(
    project_id: str,
    body: CreateRoomRequest,
    owner: SessionOwner = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
) -> RoomSummary:
    repo = ProjectRepository(settings)
    rm = repo.create_room(
        owner_id_hash=owner.id_hash,
        project_id=project_id,
        name=body.name,
        room_type=body.room_type,
        sort_order=body.sort_order,
    )
    return _format_room(rm, owner.id_hash, settings)


@router.get("/api/rooms/{room_id}", response_model=RoomSummary)
def get_room(
    room_id: str,
    owner: SessionOwner = Depends(require_owner),
    settings: Settings = Depends(get_settings),
) -> RoomSummary:
    repo = ProjectRepository(settings)
    rm = repo.get_room_owned(owner_id_hash=owner.id_hash, room_id=room_id)
    return _format_room(rm, owner.id_hash, settings)


@router.patch("/api/rooms/{room_id}", response_model=RoomSummary)
def update_room(
    room_id: str,
    body: UpdateRoomRequest,
    owner: SessionOwner = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
) -> RoomSummary:
    repo = ProjectRepository(settings)
    rm = repo.update_room(
        owner_id_hash=owner.id_hash,
        room_id=room_id,
        name=body.name,
        room_type=body.room_type,
        sort_order=body.sort_order,
    )
    return _format_room(rm, owner.id_hash, settings)
