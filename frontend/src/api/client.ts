import {
  AssetMetadataResponse,
  BriefRevisionResponse,
  Change,
  ConnectionStatusResponse,
  ExportResponse,
  GenerationAdmissionResponse,
  GenerationSnapshotResponse,
  PresentationClipItem,
  PresentationJobResponse,
  ProjectListResponse,
  ProjectSummary,
  QuoteOptions,
  QuoteResponse,
  ReviewChecklistPayload,
  ReviewResponse,
  RoomAnnotation,
  RoomSummary,
  SafeErrorBody,
  SessionResponse,
} from './types';

let currentCsrfToken = '';

export function setCsrfToken(token: string): void {
  currentCsrfToken = token;
}

export function readCsrfToken(): string {
  return currentCsrfToken;
}

export class SafeAppClientError extends Error implements SafeErrorBody {
  code: SafeErrorBody['code'];
  retryable: boolean;
  next_action: string;
  correlation_id: string;
  status: number;

  constructor(body: SafeErrorBody, status: number) {
    super(body.message);
    this.name = 'SafeAppClientError';
    this.code = body.code;
    this.retryable = body.retryable;
    this.next_action = body.next_action;
    this.correlation_id = body.correlation_id;
    this.status = status;
  }
}

export async function readSafeAppError(response: Response): Promise<SafeAppClientError> {
  const fallbackCorrelation = response.headers.get('X-Correlation-ID') || 'req_unknown';
  try {
    const data = await response.json();
    if (data && typeof data === 'object' && data.error && typeof data.error.message === 'string') {
      return new SafeAppClientError(
        {
          code: data.error.code || 'internal_error',
          message: data.error.message,
          retryable: Boolean(data.error.retryable),
          next_action: data.error.next_action || 'none',
          correlation_id: data.error.correlation_id || fallbackCorrelation,
        },
        response.status
      );
    }
  } catch {
    // Ignore JSON parse error and return safe fallback
  }
  return new SafeAppClientError(
    {
      code: 'internal_error',
      message: `Request failed (${response.status}). Please try again.`,
      retryable: response.status >= 500,
      next_action: 'retry',
      correlation_id: fallbackCorrelation,
    },
    response.status
  );
}

let pendingSessionPromise: Promise<SessionResponse> | null = null;

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const method = (init?.method || 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD' && url !== '/api/session') {
    if (pendingSessionPromise) {
      await pendingSessionPromise;
    } else if (!currentCsrfToken) {
      await apiClient.initSession();
    }
  }
  const headers = new Headers(init?.headers || {});
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }
  if (method !== 'GET' && method !== 'HEAD') {
    if (currentCsrfToken) {
      headers.set('X-CSRF-Token', currentCsrfToken);
    }
  }
  const response = await fetch(url, {
    ...init,
    method,
    credentials: 'same-origin',
    headers,
  });
  if (!response.ok) {
    throw await readSafeAppError(response);
  }
  return response.json() as Promise<T>;
}

export const apiClient = {
  async initSession(): Promise<SessionResponse> {
    if (pendingSessionPromise) {
      return pendingSessionPromise;
    }
    pendingSessionPromise = (async () => {
      try {
        const res = await requestJson<SessionResponse>('/api/session', { method: 'POST' });
        setCsrfToken(res.csrf_token);
        return res;
      } finally {
        pendingSessionPromise = null;
      }
    })();
    return pendingSessionPromise;
  },

  async connectMagicHour(key: string): Promise<ConnectionStatusResponse> {
    return requestJson<ConnectionStatusResponse>('/api/connections/magic-hour', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    });
  },

  async getConnectionStatus(): Promise<ConnectionStatusResponse> {
    return requestJson<ConnectionStatusResponse>('/api/connections/magic-hour');
  },

  async refreshConnectionBalance(): Promise<ConnectionStatusResponse> {
    return requestJson<ConnectionStatusResponse>('/api/connections/magic-hour/refresh', {
      method: 'POST',
    });
  },

  async disconnectMagicHour(): Promise<ConnectionStatusResponse> {
    return requestJson<ConnectionStatusResponse>('/api/connections/magic-hour', {
      method: 'DELETE',
    });
  },

  async listProjects(): Promise<ProjectListResponse> {
    return requestJson<ProjectListResponse>('/api/projects');
  },

  async getProject(projectId: string): Promise<ProjectSummary> {
    return requestJson<ProjectSummary>(`/api/projects/${encodeURIComponent(projectId)}`);
  },

  async createProject(name: string): Promise<ProjectSummary> {
    return requestJson<ProjectSummary>('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
  },

  async deleteProject(projectId: string): Promise<{ id: string; status: string }> {
    return requestJson<{ id: string; status: string }>(`/api/projects/${encodeURIComponent(projectId)}`, {
      method: 'DELETE',
    });
  },

  async createRoom(projectId: string, name: string, roomType: string, sortOrder?: number): Promise<RoomSummary> {
    return requestJson<RoomSummary>(`/api/projects/${encodeURIComponent(projectId)}/rooms`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, room_type: roomType, sort_order: sortOrder }),
    });
  },

  async updateRoom(
    roomId: string,
    payload: { name?: string; room_type?: string; sort_order?: number }
  ): Promise<RoomSummary> {
    return requestJson<RoomSummary>(`/api/rooms/${encodeURIComponent(roomId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },

  async uploadRoomPhoto(roomId: string, file: File): Promise<AssetMetadataResponse> {
    return requestJson<AssetMetadataResponse>(`/api/rooms/${encodeURIComponent(roomId)}/assets`, {
      method: 'POST',
      headers: {
        'Content-Type': file.type || 'image/jpeg',
      },
      body: file,
    });
  },

  async getAssetMetadata(assetId: string): Promise<AssetMetadataResponse> {
    return requestJson<AssetMetadataResponse>(`/api/assets/${encodeURIComponent(assetId)}`);
  },

  async updateAssetAnnotations(assetId: string, annotations: RoomAnnotation[]): Promise<AssetMetadataResponse> {
    return requestJson<AssetMetadataResponse>(`/api/assets/${encodeURIComponent(assetId)}/annotations`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ annotations }),
    });
  },

  async saveRoomBrief(
    roomId: string,
    payload: {
      raw_text: string;
      changes?: Change[];
      preserve?: string[];
      layout_mode?: 'preserve' | 'conceptual_change';
      style?: string | null;
      resolve_conflicts?: string[];
      parent_revision_id?: string | null;
      accepted_reference_asset_id?: string | null;
      annotations?: RoomAnnotation[];
    }
  ): Promise<BriefRevisionResponse> {
    return requestJson<BriefRevisionResponse>(`/api/rooms/${encodeURIComponent(roomId)}/briefs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },

  async getLatestRoomBrief(roomId: string): Promise<BriefRevisionResponse | null> {
    return requestJson<BriefRevisionResponse | null>(`/api/rooms/${encodeURIComponent(roomId)}/briefs`);
  },

  async createQuote(
    briefId: string,
    kind: 'image' | 'video',
    model?: string | null,
    options?: QuoteOptions
  ): Promise<QuoteResponse> {
    return requestJson<QuoteResponse>('/api/quotes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ brief_id: briefId, kind, model, options: options || {} }),
    });
  },

  async startGeneration(
    quoteId: string,
    requestKey: string,
    options?: {
      kind?: 'image' | 'video';
      resolution?: string | null;
      model?: string | null;
      file_path?: string | null;
      prompt?: string | null;
      room_id?: string | null;
    }
  ): Promise<GenerationAdmissionResponse> {
    const response = await fetch('/api/generations', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': readCsrfToken(),
      },
      body: JSON.stringify({
        quote_id: quoteId,
        idempotency_key: requestKey,
        kind: options?.kind,
        resolution: options?.resolution,
        model: options?.model,
        file_path: options?.file_path,
        prompt: options?.prompt,
        room_id: options?.room_id,
      }),
    });
    if (!response.ok) throw await readSafeAppError(response);
    return response.json();
  },

  async getGeneration(
    jobId: string,
    options?: { provider_id?: string; kind?: string; room_id?: string }
  ): Promise<GenerationSnapshotResponse> {
    let url = `/api/generations/${encodeURIComponent(jobId)}`;
    const params = new URLSearchParams();
    if (options?.provider_id) params.set('provider_id', options.provider_id);
    if (options?.kind) params.set('kind', options.kind);
    if (options?.room_id) params.set('room_id', options.room_id);
    const q = params.toString();
    if (q) url += `?${q}`;
    return requestJson<GenerationSnapshotResponse>(url);
  },

  async resumeGeneration(
    jobId: string,
    payload: { quote_id?: string | null; confirm_not_in_dashboard?: boolean }
  ): Promise<GenerationSnapshotResponse> {
    return requestJson<GenerationSnapshotResponse>(`/api/generations/${encodeURIComponent(jobId)}/resume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },

  async stopGeneration(jobId: string): Promise<GenerationSnapshotResponse> {
    return requestJson<GenerationSnapshotResponse>(`/api/generations/${encodeURIComponent(jobId)}/stop`, {
      method: 'POST',
    });
  },

  async submitReview(
    assetId: string,
    decision: 'accept' | 'revise' | 'reject',
    checklist: ReviewChecklistPayload,
    notes?: string
  ): Promise<ReviewResponse> {
    return requestJson<ReviewResponse>(`/api/assets/${encodeURIComponent(assetId)}/reviews`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, checklist, notes }),
    });
  },

  async createPresentation(
    projectId: string,
    title: string,
    orderedClips: PresentationClipItem[],
    includeConceptLabel = true
  ): Promise<PresentationJobResponse> {
    return requestJson<PresentationJobResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/presentations`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          ordered_clips: orderedClips,
          include_concept_label: includeConceptLabel,
        }),
      }
    );
  },

  async getExport(exportId: string): Promise<ExportResponse> {
    return requestJson<ExportResponse>(`/api/exports/${encodeURIComponent(exportId)}`);
  },
};
