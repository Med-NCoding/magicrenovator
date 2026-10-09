from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field
from app.domain.states import JobState


class Change(BaseModel):
    target: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=400)
    source: Literal["user_text", "user_control"] = "user_control"


class RenovationBrief(BaseModel):
    room_type: str = Field(max_length=60)
    raw_request: str = Field(min_length=1, max_length=2000)
    changes: list[Change] = Field(default_factory=list, max_length=20)
    preserve: list[str] = Field(default_factory=list, max_length=20)
    layout_mode: Literal["preserve", "conceptual_change"] = "preserve"
    style: str | None = Field(default=None, max_length=120)
    unresolved: list[str] = Field(default_factory=list, max_length=10)
    compiler_version: str = "reno-brief-v1"


class RoomAnnotation(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(default=0.1, ge=0.0, le=1.0)
    height: float = Field(default=0.1, ge=0.0, le=1.0)


class SessionResponse(BaseModel):
    session_active: bool
    csrf_token: str
    expires_at: str
    retention_days: int
    gateway_mode: Literal["live"] = "live"


class ConnectKeyRequest(BaseModel):
    key: str = Field(min_length=8, max_length=256)


class ConnectionStatusResponse(BaseModel):
    connected: bool
    masked_key: str | None = None
    tier: Literal["free", "creator", "pro", "business"] | None = None
    credits: int | None = None
    checked_at: str | None = None
    expires_at: str | None = None
    can_generate_paid: bool = False
    gateway_mode: Literal["live"] = "live"
    message: str | None = None


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class RoomSummary(BaseModel):
    id: str
    project_id: str
    name: str
    room_type: str
    sort_order: int
    primary_asset_id: str | None = None
    thumbnail_url: str | None = None
    active_brief_revision_id: str | None = None
    accepted_image_asset_id: str | None = None
    accepted_image_url: str | None = None
    accepted_image_review_id: str | None = None
    accepted_clip_asset_id: str | None = None
    accepted_clip_url: str | None = None
    accepted_clip_review_id: str | None = None
    latest_job_id: str | None = None


class ProjectSummary(BaseModel):
    id: str
    name: str
    is_mock_seed: bool = False
    room_count: int = 0
    created_at: str
    expires_at: str
    rooms: list[RoomSummary] = Field(default_factory=list)


class ProjectListResponse(BaseModel):
    items: list[ProjectSummary]
    next_cursor: str | None = None


class CreateRoomRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    room_type: str = Field(min_length=1, max_length=60)
    sort_order: int | None = None


class UpdateRoomRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    room_type: str | None = Field(default=None, min_length=1, max_length=60)
    sort_order: int | None = None


class AssetMetadataResponse(BaseModel):
    id: str
    room_id: str | None = None
    project_id: str
    role: str
    mime_type: str
    bytes_size: int
    source_width: int | None = None
    source_height: int | None = None
    width: int
    height: int
    duration_seconds: float | None = None
    orientation_applied: bool = False
    alpha_flattened: bool = False
    blur_advisory: bool = False
    advisory_message: str | None = None
    thumbnail_url: str
    download_url: str
    annotations: list[RoomAnnotation] = Field(default_factory=list)
    created_at: str


class CreateBriefRequest(BaseModel):
    raw_text: str = Field(min_length=1, max_length=2000)
    changes: list[Change] | None = None
    preserve: list[str] | None = None
    layout_mode: Literal["preserve", "conceptual_change"] = "preserve"
    style: str | None = Field(default=None, max_length=120)
    resolve_conflicts: list[str] = Field(default_factory=list)
    parent_revision_id: str | None = None
    accepted_reference_asset_id: str | None = None
    annotations: list[RoomAnnotation] = Field(default_factory=list)


class BriefRevisionResponse(BaseModel):
    id: str
    room_id: str
    parent_revision_id: str | None = None
    source_asset_id: str | None = None
    accepted_reference_asset_id: str | None = None
    revision_number: int
    brief: RenovationBrief
    compiled_prompt: str
    source_hash: str
    compiler_version: str
    has_unresolved_conflicts: bool
    quote_eligible: bool
    submitted: bool
    created_at: str


class QuoteOptions(BaseModel):
    resolution: Literal["640px", "1k", "2k", "4k", "360p", "480p", "720p", "1080p"] | None = None
    image_count: int = Field(default=1, ge=1, le=1)
    duration_seconds: int = Field(default=5, ge=3, le=15)
    audio: bool = False
    motion_preset: Literal["nearly_still", "gentle_push", "small_lateral"] = "gentle_push"
    quality_label: Literal["Draft", "Presentation"] | None = None
    anticipate_video: bool = True
    allow_direct_video: bool = False


class CreateQuoteRequest(BaseModel):
    brief_id: str
    kind: Literal["image", "video"]
    model: str | None = None
    options: QuoteOptions = Field(default_factory=QuoteOptions)


class QuoteResponse(BaseModel):
    quote_id: str
    kind: Literal["image", "video"]
    brief_revision_id: str
    source_asset_id: str
    model: str
    quality_label: str
    resolution: str
    image_count: int = 1
    duration_seconds: int | None = None
    audio: bool = False
    motion_preset: str | None = None
    estimated_credits: int
    authorized_max_credits: int
    anticipated_clip_credits: int | None = None
    anticipated_total_workflow_credits: int | None = None
    balance: int
    balance_checked_at: str
    sufficient_credits: bool
    catalog_version: str
    expires_at: str
    requires_confirmation: bool = True


class CreateGenerationRequest(BaseModel):
    quote_id: str
    idempotency_key: str = Field(min_length=8, max_length=128)


class GenerationAdmissionResponse(BaseModel):
    job_id: str
    state: JobState
    status_route: str
    events_route: str
    quote_id: str
    idempotency_key: str


class JobEventRecord(BaseModel):
    sequence: int
    job_id: str
    state: JobState
    safe_message: str
    timestamp: str
    payload: dict[str, Any] = Field(default_factory=dict)


class GenerationSnapshotResponse(BaseModel):
    job_id: str
    project_id: str
    room_id: str
    brief_revision_id: str
    quote_id: str
    kind: Literal["image", "video"]
    state: JobState
    provider_state: str | None = None
    permitted_next_action: str
    model: str
    resolution: str
    source_asset_id: str
    source_asset_url: str | None = None
    output_asset_id: str | None = None
    output_asset_url: str | None = None
    brief_outdated: bool = False
    estimated_credits: int
    observed_credits_charged: int | None = None
    correlation_name: str
    provider_id: str | None = None
    last_safe_error: dict[str, Any] | None = None
    created_at: str
    updated_at: str
    events: list[JobEventRecord] = Field(default_factory=list)


class ResumeGenerationRequest(BaseModel):
    quote_id: str | None = None
    confirm_not_in_dashboard: bool = False


class ReviewChecklistPayload(BaseModel):
    room_shape_preserved: bool = True
    doors_windows_preserved: bool = True
    fixtures_preserved: bool = True
    materials_colors_accurate: bool = True
    no_unwanted_additions: bool = True
    no_visible_distortions: bool = True
    temporal_stability: bool | None = None
    no_bent_edges_or_moving_cabinets: bool | None = None
    no_impossible_extensions: bool | None = None
    camera_movement_suitable: bool | None = None


class CreateReviewRequest(BaseModel):
    decision: Literal["accept", "revise", "reject"]
    checklist: ReviewChecklistPayload = Field(default_factory=ReviewChecklistPayload)
    notes: str | None = Field(default=None, max_length=2000)


class ReviewResponse(BaseModel):
    id: str
    asset_id: str
    room_id: str
    brief_revision_id: str
    decision: Literal["accept", "revise", "reject"]
    checklist: ReviewChecklistPayload
    notes: str | None = None
    next_brief_revision_id: str | None = None
    next_estimated_credits: int | None = None
    created_at: str


class PresentationClipItem(BaseModel):
    asset_id: str
    room_label: str = Field(min_length=1, max_length=60)


class CreatePresentationRequest(BaseModel):
    title: str = Field(default="Renovation concept", min_length=1, max_length=100)
    ordered_clips: list[PresentationClipItem] = Field(default_factory=list, max_length=5)
    include_concept_label: bool = True


class PresentationJobResponse(BaseModel):
    export_id: str
    presentation_id: str
    status: Literal["queued", "rendering", "ready", "failed"]
    manifest_hash: str
    status_route: str


class ExportMediaItem(BaseModel):
    room_id: str
    room_name: str
    kind: Literal["image", "video"]
    asset_id: str
    filename: str
    download_url: str


class ExportResponse(BaseModel):
    export_id: str
    project_id: str
    presentation_id: str
    status: Literal["queued", "rendering", "ready", "failed"]
    manifest_hash: str
    presentation_video_url: str | None = None
    brief_markdown_url: str | None = None
    brief_markdown: str | None = None
    room_media: list[ExportMediaItem] = Field(default_factory=list)
    concept_limitation_notice: str = (
        "Visual concept. Room-by-room renovation concept — not a validated 3D reconstruction, "
        "continuous floor-plan walkthrough, or construction drawing. Confirm measurements, "
        "materials, and feasibility with your renovator."
    )
    expires_at: str
