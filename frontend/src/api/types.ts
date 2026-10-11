// Generated and synchronized from backend/app/domain/schemas.py OpenAPI contract

export type ErrorCode =
  | 'not_connected'
  | 'invalid_key'
  | 'insufficient_credits'
  | 'unsupported_model'
  | 'invalid_image'
  | 'stale_quote'
  | 'rate_limited'
  | 'provider_unavailable'
  | 'unknown_submission'
  | 'save_failed'
  | 'expired_session'
  | 'not_found'
  | 'conflict'
  | 'unresolved_brief'
  | 'csrf_invalid'
  | 'generations_paused'
  | 'room_limit_reached'
  | 'concurrency_limit_reached'
  | 'validation_error'
  | 'internal_error';

export type JobState =
  | 'admitted'
  | 'preparing'
  | 'waiting_for_key'
  | 'blocked_credits'
  | 'submitting'
  | 'submission_unknown'
  | 'queued'
  | 'rendering'
  | 'saving_output'
  | 'ready_for_review'
  | 'accepted'
  | 'rejected'
  | 'failed'
  | 'stopped';

export interface SafeErrorBody {
  code: ErrorCode;
  message: string;
  retryable: boolean;
  next_action: string;
  correlation_id: string;
}

export interface ErrorEnvelope {
  error: SafeErrorBody;
}

export interface SessionResponse {
  session_active: boolean;
  csrf_token: string;
  expires_at: string;
  retention_days: number;
  gateway_mode: 'live';
}

export interface ConnectionStatusResponse {
  connected: boolean;
  masked_key?: string | null;
  tier?: 'free' | 'creator' | 'pro' | 'business' | null;
  credits?: number | null;
  checked_at?: string | null;
  expires_at?: string | null;
  can_generate_paid: boolean;
  gateway_mode: 'live';
  message?: string | null;
}

export interface RoomSummary {
  id: string;
  project_id: string;
  name: string;
  room_type: string;
  sort_order: number;
  primary_asset_id?: string | null;
  thumbnail_url?: string | null;
  active_brief_revision_id?: string | null;
  accepted_image_asset_id?: string | null;
  accepted_image_url?: string | null;
  accepted_image_review_id?: string | null;
  accepted_clip_asset_id?: string | null;
  accepted_clip_url?: string | null;
  accepted_clip_review_id?: string | null;
  latest_job_id?: string | null;
  file_path?: string | null;
}

export interface ProjectSummary {
  id: string;
  name: string;
  is_mock_seed?: boolean;
  room_count: number;
  created_at: string;
  expires_at: string;
  rooms: RoomSummary[];
}

export interface ProjectListResponse {
  items: ProjectSummary[];
  next_cursor?: string | null;
}

export interface RoomAnnotation {
  label: string;
  x: number;
  y: number;
  width?: number;
  height?: number;
}

export interface AssetMetadataResponse {
  id: string;
  room_id?: string | null;
  project_id: string;
  role: string;
  mime_type: string;
  bytes_size: number;
  source_width?: number | null;
  source_height?: number | null;
  width: number;
  height: number;
  duration_seconds?: number | null;
  orientation_applied: boolean;
  alpha_flattened: boolean;
  blur_advisory: boolean;
  advisory_message?: string | null;
  thumbnail_url: string;
  download_url: string;
  file_path?: string;
  annotations: RoomAnnotation[];
  created_at: string;
}

export interface Change {
  target: string;
  description: string;
  source: 'user_text' | 'user_control';
}

export interface RenovationBrief {
  room_type: string;
  raw_request: string;
  changes: Change[];
  preserve: string[];
  layout_mode: 'preserve' | 'conceptual_change';
  style?: string | null;
  unresolved: string[];
  compiler_version: string;
}

export interface BriefRevisionResponse {
  id: string;
  room_id: string;
  parent_revision_id?: string | null;
  source_asset_id?: string | null;
  accepted_reference_asset_id?: string | null;
  revision_number: number;
  brief: RenovationBrief;
  compiled_prompt: string;
  source_hash: string;
  compiler_version: string;
  has_unresolved_conflicts: boolean;
  quote_eligible: boolean;
  submitted: boolean;
  created_at: string;
}

export interface QuoteOptions {
  resolution?: '640px' | '1k' | '2k' | '4k' | '360p' | '480p' | '720p' | '1080p' | null;
  image_count?: number;
  duration_seconds?: number;
  audio?: boolean;
  motion_preset?: 'nearly_still' | 'gentle_push' | 'small_lateral';
  quality_label?: 'Draft' | 'Presentation' | null;
  anticipate_video?: boolean;
  allow_direct_video?: boolean;
}

export interface QuoteResponse {
  quote_id: string;
  kind: 'image' | 'video';
  brief_revision_id: string;
  source_asset_id: string;
  model: string;
  quality_label: string;
  resolution: string;
  image_count: number;
  duration_seconds?: number | null;
  audio: boolean;
  motion_preset?: string | null;
  estimated_credits: number;
  authorized_max_credits: number;
  anticipated_clip_credits?: number | null;
  anticipated_total_workflow_credits?: number | null;
  balance: number;
  balance_checked_at: string;
  sufficient_credits: boolean;
  catalog_version: string;
  expires_at: string;
  requires_confirmation: boolean;
}

export interface GenerationAdmissionResponse {
  job_id: string;
  id?: string;
  provider_id?: string;
  room_id?: string;
  kind?: 'image' | 'video';
  model?: string;
  resolution?: string;
  state: JobState;
  status_route: string;
  events_route: string;
  quote_id: string;
  idempotency_key: string;
  safe_message?: string;
}

export interface JobEventRecord {
  sequence: number;
  job_id: string;
  state: JobState;
  safe_message: string;
  timestamp: string;
  payload: Record<string, unknown>;
}

export interface GenerationSnapshotResponse {
  job_id: string;
  project_id: string;
  room_id: string;
  brief_revision_id: string;
  quote_id: string;
  kind: 'image' | 'video';
  state: JobState;
  provider_state?: string | null;
  permitted_next_action: string;
  model: string;
  resolution: string;
  source_asset_id: string;
  source_asset_url?: string | null;
  output_asset_id?: string | null;
  output_asset_url?: string | null;
  output_url?: string | null;
  output_data_url?: string | null;
  brief_outdated: boolean;
  estimated_credits: number;
  observed_credits_charged?: number | null;
  correlation_name: string;
  provider_id?: string | null;
  last_safe_error?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  events: JobEventRecord[];
}

export interface ReviewChecklistPayload {
  room_shape_preserved: boolean;
  doors_windows_preserved: boolean;
  fixtures_preserved: boolean;
  materials_colors_accurate: boolean;
  no_unwanted_additions: boolean;
  no_visible_distortions: boolean;
  temporal_stability?: boolean | null;
  no_bent_edges_or_moving_cabinets?: boolean | null;
  no_impossible_extensions?: boolean | null;
  camera_movement_suitable?: boolean | null;
}

export interface ReviewResponse {
  id: string;
  asset_id: string;
  room_id: string;
  brief_revision_id: string;
  decision: 'accept' | 'revise' | 'reject';
  checklist: ReviewChecklistPayload;
  notes?: string | null;
  next_brief_revision_id?: string | null;
  next_estimated_credits?: number | null;
  created_at: string;
}

export interface PresentationClipItem {
  asset_id: string;
  room_label: string;
}

export interface PresentationJobResponse {
  export_id: string;
  presentation_id: string;
  status: 'queued' | 'rendering' | 'ready' | 'failed';
  manifest_hash: string;
  status_route: string;
}

export interface ExportMediaItem {
  room_id: string;
  room_name: string;
  kind: 'image' | 'video';
  asset_id: string;
  filename: string;
  download_url: string;
}

export interface ExportResponse {
  export_id: string;
  project_id: string;
  presentation_id: string;
  status: 'queued' | 'rendering' | 'ready' | 'failed';
  manifest_hash: string;
  presentation_video_url?: string | null;
  brief_markdown_url?: string | null;
  brief_markdown?: string | null;
  room_media: ExportMediaItem[];
  concept_limitation_notice: string;
  expires_at: string;
}
