-- 001_initial_schema.sql
-- Durable schema for RenoPreview (PostgreSQL)

CREATE TABLE IF NOT EXISTS sessions (
    id_hash TEXT PRIMARY KEY,
    csrf_token TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS credential_references (
    id TEXT PRIMARY KEY,
    owner_id_hash TEXT NOT NULL REFERENCES sessions(id_hash) ON DELETE CASCADE,
    vault_ref TEXT NOT NULL,
    key_fingerprint TEXT NOT NULL,
    masked_suffix TEXT NOT NULL,
    provider_account_fingerprint TEXT NOT NULL,
    tier TEXT NOT NULL,
    balance INTEGER NOT NULL DEFAULT 0,
    balance_checked_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    disconnected_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_cred_ref_owner ON credential_references(owner_id_hash);
CREATE INDEX IF NOT EXISTS idx_cred_ref_account ON credential_references(provider_account_fingerprint);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    owner_id_hash TEXT NOT NULL REFERENCES sessions(id_hash) ON DELETE CASCADE,
    name TEXT NOT NULL,
    is_mock_seed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    cleanup_status TEXT NOT NULL DEFAULT 'active',
    cleanup_attempts INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id_hash, created_at DESC);

CREATE TABLE IF NOT EXISTS rooms (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    room_type TEXT NOT NULL,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    primary_asset_id TEXT,
    active_brief_revision_id TEXT,
    accepted_image_asset_id TEXT,
    accepted_image_review_id TEXT,
    accepted_clip_asset_id TEXT,
    accepted_clip_review_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_rooms_project ON rooms(project_id, sort_order ASC);

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    owner_id_hash TEXT NOT NULL REFERENCES sessions(id_hash) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    room_id TEXT REFERENCES rooms(id) ON DELETE SET NULL,
    role TEXT NOT NULL,
    storage_key TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    bytes_size INTEGER NOT NULL,
    source_width INTEGER,
    source_height INTEGER,
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    duration_seconds DOUBLE PRECISION,
    fps DOUBLE PRECISION,
    codec TEXT,
    orientation_applied BOOLEAN NOT NULL DEFAULT FALSE,
    alpha_flattened BOOLEAN NOT NULL DEFAULT FALSE,
    blur_advisory BOOLEAN NOT NULL DEFAULT FALSE,
    annotations_json TEXT NOT NULL DEFAULT '[]',
    normalization_transform_json TEXT NOT NULL DEFAULT '{}',
    provider_file_paths_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_assets_owner_project ON assets(owner_id_hash, project_id);
CREATE INDEX IF NOT EXISTS idx_assets_room ON assets(room_id);

CREATE TABLE IF NOT EXISTS brief_revisions (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    parent_revision_id TEXT REFERENCES brief_revisions(id) ON DELETE SET NULL,
    source_asset_id TEXT REFERENCES assets(id) ON DELETE SET NULL,
    accepted_reference_asset_id TEXT REFERENCES assets(id) ON DELETE SET NULL,
    revision_number INTEGER NOT NULL DEFAULT 1,
    raw_text TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    compiled_prompt TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    compiler_version TEXT NOT NULL DEFAULT 'reno-brief-v1',
    has_unresolved_conflicts BOOLEAN NOT NULL DEFAULT FALSE,
    submitted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brief_revisions_room ON brief_revisions(room_id, revision_number DESC);

CREATE TABLE IF NOT EXISTS quotes (
    id TEXT PRIMARY KEY,
    owner_id_hash TEXT NOT NULL REFERENCES sessions(id_hash) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    brief_revision_id TEXT NOT NULL REFERENCES brief_revisions(id) ON DELETE CASCADE,
    source_asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    source_review_id TEXT,
    kind TEXT NOT NULL,
    model TEXT NOT NULL,
    resolution TEXT NOT NULL,
    image_count INTEGER NOT NULL DEFAULT 1,
    duration_seconds INTEGER,
    audio BOOLEAN NOT NULL DEFAULT FALSE,
    motion_preset TEXT,
    motion_prompt TEXT,
    spec_hash TEXT NOT NULL,
    estimated_credits INTEGER NOT NULL,
    authorized_max_credits INTEGER NOT NULL,
    anticipated_clip_credits INTEGER,
    balance_snapshot INTEGER NOT NULL,
    balance_checked_at TIMESTAMPTZ NOT NULL,
    catalog_version TEXT NOT NULL,
    requires_confirmation BOOLEAN NOT NULL DEFAULT TRUE,
    confirmed_at TIMESTAMPTZ,
    consumed_by_job_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_quotes_owner ON quotes(owner_id_hash, created_at DESC);

CREATE TABLE IF NOT EXISTS generations (
    id TEXT PRIMARY KEY,
    owner_id_hash TEXT NOT NULL REFERENCES sessions(id_hash) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    brief_revision_id TEXT NOT NULL REFERENCES brief_revisions(id) ON DELETE CASCADE,
    quote_id TEXT NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    provider_state TEXT,
    source_asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    source_review_id TEXT,
    output_asset_id TEXT REFERENCES assets(id) ON DELETE SET NULL,
    model TEXT NOT NULL,
    options_json TEXT NOT NULL,
    compiled_prompt TEXT NOT NULL,
    compiler_version TEXT NOT NULL,
    catalog_version TEXT NOT NULL,
    provider_id TEXT,
    correlation_name TEXT NOT NULL,
    account_fingerprint TEXT,
    observed_credits_charged INTEGER,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_poll_at TIMESTAMPTZ,
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    last_safe_error_json TEXT,
    reconciliation_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(owner_id_hash, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_generations_owner ON generations(owner_id_hash, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generations_room ON generations(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generations_state_poll ON generations(state, next_poll_at);
CREATE INDEX IF NOT EXISTS idx_generations_account_active ON generations(account_fingerprint, state);

CREATE TABLE IF NOT EXISTS provider_attempts (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES generations(id) ON DELETE CASCADE,
    state TEXT NOT NULL,
    provider_id TEXT,
    account_fingerprint TEXT,
    request_payload_json TEXT NOT NULL,
    response_status INTEGER,
    observed_credits INTEGER,
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_provider_attempts_job ON provider_attempts(job_id, created_at ASC);

CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    owner_id_hash TEXT NOT NULL REFERENCES sessions(id_hash) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    job_id TEXT REFERENCES generations(id) ON DELETE SET NULL,
    brief_revision_id TEXT NOT NULL REFERENCES brief_revisions(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    decision TEXT NOT NULL,
    checklist_json TEXT NOT NULL,
    notes TEXT,
    reviewer TEXT NOT NULL DEFAULT 'human_owner',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reviews_asset ON reviews(asset_id, created_at DESC);

CREATE TABLE IF NOT EXISTS credit_ledger (
    id TEXT PRIMARY KEY,
    owner_id_hash TEXT NOT NULL REFERENCES sessions(id_hash) ON DELETE CASCADE,
    account_fingerprint TEXT,
    job_id TEXT REFERENCES generations(id) ON DELETE SET NULL,
    attempt_id TEXT REFERENCES provider_attempts(id) ON DELETE SET NULL,
    quote_id TEXT REFERENCES quotes(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    estimated_amount INTEGER,
    observed_amount INTEGER,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(attempt_id, event_type)
);

CREATE INDEX IF NOT EXISTS idx_credit_ledger_owner ON credit_ledger(owner_id_hash, created_at ASC);

CREATE TABLE IF NOT EXISTS presentations (
    id TEXT PRIMARY KEY,
    owner_id_hash TEXT NOT NULL REFERENCES sessions(id_hash) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    ordered_clips_json TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    include_concept_label BOOLEAN NOT NULL DEFAULT TRUE,
    assembler_version TEXT NOT NULL DEFAULT 'presentation-v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_presentations_project ON presentations(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS exports (
    id TEXT PRIMARY KEY,
    owner_id_hash TEXT NOT NULL REFERENCES sessions(id_hash) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    presentation_id TEXT NOT NULL REFERENCES presentations(id) ON DELETE CASCADE,
    manifest_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    video_asset_id TEXT REFERENCES assets(id) ON DELETE SET NULL,
    brief_asset_id TEXT REFERENCES assets(id) ON DELETE SET NULL,
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    last_safe_error_json TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exports_project_hash ON exports(project_id, manifest_hash);

CREATE TABLE IF NOT EXISTS job_events (
    sequence BIGSERIAL PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES generations(id) ON DELETE CASCADE,
    state TEXT NOT NULL,
    safe_message TEXT NOT NULL,
    safe_payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_job_events_job_seq ON job_events(job_id, sequence ASC);

CREATE TABLE IF NOT EXISTS outbox (
    id TEXT PRIMARY KEY,
    job_id TEXT REFERENCES generations(id) ON DELETE CASCADE,
    export_id TEXT REFERENCES exports(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    dispatched BOOLEAN NOT NULL DEFAULT FALSE,
    dispatched_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outbox_undispatched ON outbox(dispatched, created_at ASC);
