from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends

from app.dependencies import SessionOwner, require_csrf, require_owner
from app.domain.schemas import BriefRevisionResponse, CreateBriefRequest
from app.services.compiler import BriefService
from app.settings import Settings, get_settings

router = APIRouter(tags=["briefs"])


@router.post("/api/rooms/{room_id}/briefs", response_model=BriefRevisionResponse, status_code=201)
def create_or_update_room_brief(
    room_id: str,
    body: CreateBriefRequest,
    owner: SessionOwner = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
) -> BriefRevisionResponse:
    svc = BriefService(settings)
    return svc.save_room_brief(
        owner_id_hash=owner.id_hash,
        room_id=room_id,
        body=body,
    )


@router.get("/api/rooms/{room_id}/briefs", response_model=Optional[BriefRevisionResponse])
def get_latest_room_brief(
    room_id: str,
    owner: SessionOwner = Depends(require_owner),
    settings: Settings = Depends(get_settings),
) -> BriefRevisionResponse | None:
    svc = BriefService(settings)
    return svc.get_latest_room_brief(
        owner_id_hash=owner.id_hash,
        room_id=room_id,
    )
