from __future__ import annotations

import json
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.dependencies import SessionOwner, require_csrf, require_owner
from app.domain.errors import AppError
from app.domain.schemas import AssetMetadataResponse, RoomAnnotation
from app.services.asset_service import AssetService
from app.settings import Settings, get_settings

router = APIRouter(tags=["assets"])


class UpdateAnnotationsRequest(BaseModel):
    annotations: list[RoomAnnotation] = Field(default_factory=list, max_length=20)


@router.post("/api/rooms/{room_id}/assets", response_model=AssetMetadataResponse, status_code=201)
async def upload_room_asset(
    room_id: str,
    file: UploadFile | None = File(default=None),
    photo: UploadFile | None = File(default=None),
    annotations: str | None = Form(default=None),
    owner: SessionOwner = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
) -> AssetMetadataResponse:
    upload = file or photo
    if upload is None:
        raise AppError(
            code="invalid_image",
            message="No room photo file was provided.",
            status_code=400,
            retryable=False,
            next_action="upload_valid_image",
        )
    # Enforce upload byte limit during streaming before decoding
    chunks: list[bytes] = []
    total_read = 0
    chunk_size = 64 * 1024
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total_read += len(chunk)
        if total_read > settings.MAX_UPLOAD_BYTES:
            raise AppError(
                code="invalid_image",
                message=f"Image file exceeds the {settings.MAX_UPLOAD_BYTES // (1024 * 1024)} MiB upload limit.",
                status_code=413,
                retryable=False,
                next_action="upload_smaller_image",
            )
        chunks.append(chunk)

    raw_bytes = b"".join(chunks)
    parsed_annotations: list[RoomAnnotation] = []
    if annotations:
        try:
            raw_list = json.loads(annotations)
            if isinstance(raw_list, list):
                parsed_annotations = [RoomAnnotation(**item) for item in raw_list]
        except Exception as exc:
            raise AppError(
                code="invalid_brief",
                message="Invalid photo annotations payload.",
                status_code=400,
                retryable=False,
                next_action="fix_annotations",
            ) from exc

    svc = AssetService(settings)
    return svc.upload_room_photo(
        owner_id_hash=owner.id_hash,
        room_id=room_id,
        raw_bytes=raw_bytes,
        filename=upload.filename,
        annotations=parsed_annotations,
    )


@router.get("/api/assets/{asset_id}", response_model=AssetMetadataResponse)
def get_asset_metadata(
    asset_id: str,
    owner: SessionOwner = Depends(require_owner),
    settings: Settings = Depends(get_settings),
) -> AssetMetadataResponse:
    svc = AssetService(settings)
    return svc.get_asset_metadata(owner_id_hash=owner.id_hash, asset_id=asset_id)


@router.patch("/api/assets/{asset_id}/annotations", response_model=AssetMetadataResponse)
def update_asset_annotations(
    asset_id: str,
    body: UpdateAnnotationsRequest,
    owner: SessionOwner = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
) -> AssetMetadataResponse:
    svc = AssetService(settings)
    return svc.update_annotations(
        owner_id_hash=owner.id_hash,
        asset_id=asset_id,
        annotations=body.annotations,
    )


@router.get("/api/assets/{asset_id}/download")
def download_asset(
    asset_id: str,
    variant: str = Query(default="full"),
    exp: int = Query(...),
    sig: str = Query(...),
    download: int | None = Query(default=None),
    owner: SessionOwner = Depends(require_owner),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    svc = AssetService(settings)
    file_path, mime_type = svc.resolve_download_path(
        owner_id_hash=owner.id_hash,
        asset_id=asset_id,
        variant=variant,
        exp=exp,
        sig=sig,
    )
    ext = "mp4" if "video" in mime_type else "jpg"
    return FileResponse(
        path=str(file_path),
        media_type=mime_type,
        filename=f"renovated_{asset_id}.{ext}" if download else None,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/api/assets/{asset_id}/reviews")
def submit_asset_review(
    asset_id: str,
    body: dict,
    owner: SessionOwner = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
):
    from app.domain.schemas import CreateReviewRequest
    from app.services.review_service import ReviewService

    if isinstance(body.get("notes"), str):
        body = {**body, "notes": body["notes"].strip()[:2000]}
    req = CreateReviewRequest(**body)
    svc = ReviewService(settings)
    return svc.submit_review(owner_id_hash=owner.id_hash, asset_id=asset_id, body=req)

