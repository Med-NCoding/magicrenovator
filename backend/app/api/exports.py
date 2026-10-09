from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import SessionOwner, require_csrf, require_owner
from app.domain.schemas import (
    CreatePresentationRequest,
    ExportResponse,
    PresentationJobResponse,
)
from app.services.presentation_service import PresentationService
from app.settings import Settings, get_settings

router = APIRouter(tags=["exports"])


@router.post(
    "/api/projects/{project_id}/presentations",
    response_model=PresentationJobResponse,
    status_code=201,
)
def create_presentation_endpoint(
    project_id: str,
    body: CreatePresentationRequest,
    owner: SessionOwner = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
) -> PresentationJobResponse:
    service = PresentationService(settings)
    return service.create_presentation(
        owner_id_hash=owner.id_hash,
        project_id=project_id,
        body=body,
    )


@router.get("/api/exports/{export_id}", response_model=ExportResponse)
def get_export_endpoint(
    export_id: str,
    owner: SessionOwner = Depends(require_owner),
    settings: Settings = Depends(get_settings),
) -> ExportResponse:
    service = PresentationService(settings)
    return service.get_export(
        owner_id_hash=owner.id_hash,
        export_id=export_id,
    )
