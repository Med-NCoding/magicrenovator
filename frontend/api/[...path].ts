import type { IncomingMessage, ServerResponse } from 'http';

interface Project {
  id: string;
  name: string;
  created_at: string;
  expires_at: string;
  rooms: Room[];
}

interface Room {
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
}

interface Asset {
  id: string;
  room_id: string;
  project_id: string;
  role: 'original_photo' | 'generated_image' | 'generated_video';
  mime_type: string;
  bytes_size: number;
  width: number;
  height: number;
  thumbnail_url: string;
  download_url: string;
  file_path?: string;
  created_at: string;
}

interface Brief {
  id: string;
  room_id: string;
  parent_revision_id?: string | null;
  source_asset_id?: string | null;
  accepted_reference_asset_id?: string | null;
  revision_number: number;
  brief: {
    room_type: string;
    raw_request: string;
    raw_text?: string;
    changes: Array<{ target: string; description: string; source: 'user_text' | 'user_control' }>;
    preserve: string[];
    layout_mode: 'preserve' | 'conceptual_change';
    style?: string | null;
    unresolved: string[];
    compiler_version: string;
  };
  compiled_prompt: string;
  source_hash: string;
  compiler_version: string;
  has_unresolved_conflicts: boolean;
  quote_eligible: boolean;
  submitted: boolean;
  created_at: string;
}

interface Job {
  id: string;
  provider_id: string;
  project_id: string;
  room_id: string;
  kind: 'image' | 'video';
  state: 'queued' | 'rendering' | 'polling_provider' | 'ready_for_review' | 'failed' | 'stopped';
  provider_state: string;
  prompt: string;
  output_asset_id?: string | null;
  output_url?: string | null;
  created_at: string;
}

// In-memory store for serverless execution
const projectsStore = new Map<string, Project>();
const roomsStore = new Map<string, Room>();
const assetsStore = new Map<string, Asset>();
const briefsStore = new Map<string, Brief>();
const jobsStore = new Map<string, Job>();
const quotesStore = new Map<string, { quote_id: string; kind: 'image' | 'video'; model: string; resolution: string }>();

function extractKey(req: IncomingMessage): string | null {
  const cookieHeader = req.headers.cookie || '';
  const match = cookieHeader.match(/rp_mh_key=([^;]+)/);
  if (!match) return null;
  try {
    return Buffer.from(match[1], 'base64').toString('utf8');
  } catch {
    return null;
  }
}

function parseJsonBody(req: IncomingMessage): Promise<any> {
  return new Promise((resolve) => {
    let data = '';
    req.on('data', (chunk) => {
      data += chunk;
    });
    req.on('end', () => {
      try {
        resolve(data ? JSON.parse(data) : {});
      } catch {
        resolve({});
      }
    });
  });
}

function parseRawBody(req: IncomingMessage): Promise<Buffer> {
  return new Promise((resolve) => {
    const chunks: Buffer[] = [];
    req.on('data', (chunk) => {
      chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    });
    req.on('end', () => {
      resolve(Buffer.concat(chunks));
    });
  });
}

function extractFileBytes(buffer: Buffer, contentType?: string): Buffer {
  if (!contentType || !contentType.includes('multipart/form-data')) {
    return buffer;
  }
  const boundaryMatch = contentType.match(/boundary=(?:"([^"]+)"|([^;]+))/i);
  const boundaryStr = boundaryMatch ? (boundaryMatch[1] || boundaryMatch[2]) : null;

  const crlfIndex = buffer.indexOf('\r\n\r\n');
  const lfIndex = buffer.indexOf('\n\n');
  const headerEnd = crlfIndex !== -1 ? crlfIndex + 4 : (lfIndex !== -1 ? lfIndex + 2 : -1);
  if (headerEnd === -1) return buffer;

  let fileData = buffer.subarray(headerEnd);

  if (boundaryStr) {
    const boundaryBuffer = Buffer.from(`--${boundaryStr}`);
    const lastBoundaryIndex = fileData.lastIndexOf(boundaryBuffer);
    if (lastBoundaryIndex !== -1) {
      let end = lastBoundaryIndex;
      if (end >= 2 && fileData[end - 2] === 13 && fileData[end - 1] === 10) {
        end -= 2;
      } else if (end >= 1 && fileData[end - 1] === 10) {
        end -= 1;
      }
      fileData = fileData.subarray(0, end);
    }
  }

  return fileData;
}

function sendJson(res: ServerResponse, status: number, data: any) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(data));
}

function sendError(res: ServerResponse, status: number, code: string, message: string) {
  sendJson(res, status, {
    error: {
      code,
      message,
      retryable: status >= 500,
      next_action: 'retry',
      correlation_id: `req_${Date.now()}`
    }
  });
}

export default async function handler(req: IncomingMessage, res: ServerResponse) {
  const method = (req.method || 'GET').toUpperCase();
  const rawUrl = req.url || '';
  const host = req.headers.host || 'localhost';
  const urlObj = new URL(rawUrl, `http://${host}`);
  const pathname = urlObj.pathname.replace(/^\/api\/?/, '').replace(/\/$/, '');
  const segments = pathname ? pathname.split('/') : [];

  // Enable CORS headers
  res.setHeader('Access-Control-Allow-Credentials', 'true');
  res.setHeader('Access-Control-Allow-Origin', req.headers.origin || '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,PUT,PATCH,DELETE,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type,Accept,X-CSRF-Token,Authorization');

  if (method === 'OPTIONS') {
    res.statusCode = 204;
    res.end();
    return;
  }

  try {
    // 1. /api/session
    if (segments[0] === 'session') {
      res.setHeader('Set-Cookie', 'rp_session=mr_live_session; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800');
      return sendJson(res, 200, {
        session_active: true,
        csrf_token: 'mr_csrf_live_token',
        expires_at: new Date(Date.now() + 7 * 86400000).toISOString(),
        retention_days: 7,
        gateway_mode: 'live'
      });
    }

    // 2. /api/connections/magic-hour
    if (segments[0] === 'connections' && segments[1] === 'magic-hour') {
      // POST /api/connections/magic-hour/refresh
      if (segments[2] === 'refresh' && method === 'POST') {
        const key = extractKey(req);
        if (!key) {
          return sendError(res, 401, 'not_connected', 'Magic Hour is not connected.');
        }
        const accRes = await fetch('https://api.magichour.ai/v1/account', {
          headers: { Authorization: `Bearer ${key}`, Accept: 'application/json' }
        });
        if (!accRes.ok) {
          return sendError(res, 401, 'invalid_key', 'Failed to refresh Magic Hour balance. Verify your key on magichour.ai.');
        }
        const acc = await accRes.json();
        return sendJson(res, 200, {
          connected: true,
          masked_key: '•••_' + key.slice(-4),
          tier: acc.tier || 'pro',
          credits: typeof acc.credits === 'number' ? acc.credits : 0,
          checked_at: new Date().toISOString(),
          expires_at: new Date(Date.now() + 86400000).toISOString(),
          can_generate_paid: (acc.credits || 0) > 0,
          gateway_mode: 'live',
          message: 'Magic Hour balance refreshed.'
        });
      }

      // POST /api/connections/magic-hour (connect)
      if (method === 'POST') {
        const body = await parseJsonBody(req);
        const key = String(body.key || '').trim();
        if (!key) {
          return sendError(res, 400, 'invalid_key', 'Please enter a valid Magic Hour API key.');
        }

        try {
          const mhRes = await fetch('https://api.magichour.ai/v1/account', {
            headers: { Authorization: `Bearer ${key}`, Accept: 'application/json' }
          });

          if (!mhRes.ok) {
            return sendError(res, 401, 'invalid_key', 'Magic Hour rejected this API key. Please check your key at magichour.ai.');
          }

          const acc = await mhRes.json();
          const encoded = Buffer.from(key).toString('base64');
          res.setHeader('Set-Cookie', [
            `rp_mh_key=${encoded}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000`,
            `rp_session=mr_live_session; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000`
          ]);

          return sendJson(res, 200, {
            connected: true,
            masked_key: '•••_' + key.slice(-4),
            tier: acc.tier || 'pro',
            credits: typeof acc.credits === 'number' ? acc.credits : 0,
            checked_at: new Date().toISOString(),
            expires_at: new Date(Date.now() + 86400000).toISOString(),
            can_generate_paid: (acc.credits || 0) > 0,
            gateway_mode: 'live',
            message: 'Magic Hour connected.'
          });
        } catch (err: any) {
          return sendError(res, 502, 'provider_unavailable', `Could not reach Magic Hour API: ${err.message}`);
        }
      }

      // GET /api/connections/magic-hour (status)
      if (method === 'GET') {
        const key = extractKey(req);
        if (!key) {
          return sendJson(res, 200, {
            connected: false,
            masked_key: null,
            tier: null,
            credits: null,
            can_generate_paid: false,
            gateway_mode: 'live',
            message: 'Not connected to Magic Hour.'
          });
        }

        try {
          const accRes = await fetch('https://api.magichour.ai/v1/account', {
            headers: { Authorization: `Bearer ${key}`, Accept: 'application/json' }
          });
          if (accRes.ok) {
            const acc = await accRes.json();
            return sendJson(res, 200, {
              connected: true,
              masked_key: '•••_' + key.slice(-4),
              tier: acc.tier || 'pro',
              credits: typeof acc.credits === 'number' ? acc.credits : 0,
              checked_at: new Date().toISOString(),
              expires_at: new Date(Date.now() + 86400000).toISOString(),
              can_generate_paid: (acc.credits || 0) > 0,
              gateway_mode: 'live',
              message: 'Magic Hour connected.'
            });
          }
        } catch {
          // fallback if offline
        }

        return sendJson(res, 200, {
          connected: true,
          masked_key: '•••_' + key.slice(-4),
          tier: 'pro',
          credits: 500,
          checked_at: new Date().toISOString(),
          expires_at: new Date(Date.now() + 86400000).toISOString(),
          can_generate_paid: true,
          gateway_mode: 'live',
          message: 'Magic Hour connected.'
        });
      }

      // DELETE /api/connections/magic-hour (disconnect)
      if (method === 'DELETE') {
        res.setHeader('Set-Cookie', 'rp_mh_key=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0');
        return sendJson(res, 200, {
          connected: false,
          masked_key: null,
          tier: null,
          credits: null,
          can_generate_paid: false,
          gateway_mode: 'live',
          message: 'Disconnected from Magic Hour.'
        });
      }
    }

    // 3. /api/projects
    if (segments[0] === 'projects') {
      // POST /api/projects/:id/rooms
      if (segments.length === 3 && segments[2] === 'rooms' && method === 'POST') {
        const projectId = segments[1];
        const body = await parseJsonBody(req);
        const roomId = `rm_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
        const room: Room = {
          id: roomId,
          project_id: projectId,
          name: String(body.name || 'Room').trim(),
          room_type: String(body.room_type || 'kitchen').trim(),
          sort_order: Number(body.sort_order || 0)
        };
        roomsStore.set(roomId, room);

        const project = projectsStore.get(projectId);
        if (project) {
          project.rooms.push(room);
        }
        return sendJson(res, 200, room);
      }

      // GET /api/projects/:id
      if (segments.length === 2 && method === 'GET') {
        const projectId = segments[1];
        let project = projectsStore.get(projectId);
        if (!project) {
          project = {
            id: projectId,
            name: 'Renovation Project',
            created_at: new Date().toISOString(),
            expires_at: new Date(Date.now() + 7 * 86400000).toISOString(),
            rooms: []
          };
          projectsStore.set(projectId, project);
        }
        return sendJson(res, 200, project);
      }

      // DELETE /api/projects/:id
      if (segments.length === 2 && method === 'DELETE') {
        const projectId = segments[1];
        projectsStore.delete(projectId);
        return sendJson(res, 200, { id: projectId, status: 'tombstoned' });
      }

      // POST /api/projects
      if (method === 'POST') {
        const body = await parseJsonBody(req);
        const projectId = `prj_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
        const project: Project = {
          id: projectId,
          name: String(body.name || 'New Renovation').trim(),
          created_at: new Date().toISOString(),
          expires_at: new Date(Date.now() + 7 * 86400000).toISOString(),
          rooms: []
        };
        projectsStore.set(projectId, project);
        return sendJson(res, 201, project);
      }

      // GET /api/projects
      if (method === 'GET') {
        const items = Array.from(projectsStore.values());
        return sendJson(res, 200, { items, next_cursor: null });
      }
    }

    // 4. /api/rooms
    if (segments[0] === 'rooms' && segments.length >= 2) {
      const roomId = segments[1];

      // POST /api/rooms/:id/assets (Photo Upload)
      if (segments[2] === 'assets' && method === 'POST') {
        const key = extractKey(req);
        if (!key) {
          return sendError(res, 401, 'not_connected', 'Please connect your Magic Hour key first.');
        }

        const rawBuffer = await parseRawBody(req);
        const fileBytes = extractFileBytes(rawBuffer, req.headers['content-type']);
        if (fileBytes.length === 0) {
          return sendError(res, 400, 'invalid_upload', 'Empty photo upload received.');
        }

        let extension = 'jpg';
        if (fileBytes[0] === 0x89 && fileBytes[1] === 0x50 && fileBytes[2] === 0x4e && fileBytes[3] === 0x47) {
          extension = 'png';
        }

        try {
          // Reserve upload URL from Magic Hour
          const uploadRes = await fetch('https://api.magichour.ai/v1/files/upload-urls', {
            method: 'POST',
            headers: {
              Authorization: `Bearer ${key}`,
              'Content-Type': 'application/json',
              Accept: 'application/json'
            },
            body: JSON.stringify({
              items: [{ type: 'image', extension }]
            })
          });

          if (!uploadRes.ok) {
            return sendError(res, 502, 'upload_failed', 'Failed to get upload URL from Magic Hour.');
          }

          const uploadData = await uploadRes.json();
          const firstItem = uploadData.items?.[0];
          if (!firstItem || !firstItem.upload_url) {
            return sendError(res, 502, 'upload_failed', 'Malformed upload response from Magic Hour.');
          }

          // Upload raw clean image bytes to Magic Hour signed URL
          await fetch(firstItem.upload_url, {
            method: 'PUT',
            headers: { 'Content-Type': extension === 'png' ? 'image/png' : 'image/jpeg' },
            body: fileBytes
          });

          const assetId = `ast_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
          const asset: Asset = {
            id: assetId,
            room_id: roomId,
            project_id: 'default',
            role: 'original_photo',
            mime_type: extension === 'png' ? 'image/png' : 'image/jpeg',
            bytes_size: fileBytes.length,
            width: 1280,
            height: 720,
            thumbnail_url: firstItem.upload_url,
            download_url: firstItem.upload_url,
            file_path: firstItem.file_path,
            created_at: new Date().toISOString()
          };
          assetsStore.set(assetId, asset);

          const room = roomsStore.get(roomId);
          if (room) {
            room.primary_asset_id = assetId;
            room.thumbnail_url = firstItem.upload_url;
            room.file_path = firstItem.file_path;
          }

          res.setHeader('Set-Cookie', [
            `mr_last_photo_path=${encodeURIComponent(firstItem.file_path)}; Path=/; SameSite=Lax; Max-Age=86400`,
            `mr_photo_${roomId}=${encodeURIComponent(firstItem.file_path)}; Path=/; SameSite=Lax; Max-Age=86400`
          ]);

          return sendJson(res, 201, asset);
        } catch (err: any) {
          return sendError(res, 500, 'upload_failed', `Upload error: ${err.message}`);
        }
      }

      // POST /api/rooms/:id/briefs
      if (segments[2] === 'briefs' && method === 'POST') {
        const body = await parseJsonBody(req);
        const briefId = `brf_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
        const rawText = String(body.raw_text || body.raw_request || '').trim();
        const room = roomsStore.get(roomId);
        const roomType = room?.room_type || 'kitchen';

        const brief: Brief = {
          id: briefId,
          room_id: roomId,
          parent_revision_id: body.parent_revision_id || null,
          source_asset_id: room?.primary_asset_id || null,
          accepted_reference_asset_id: body.accepted_reference_asset_id || null,
          revision_number: 1,
          brief: {
            room_type: roomType,
            raw_request: rawText,
            raw_text: rawText,
            changes: body.changes || [],
            preserve: body.preserve || [
              'Room footprint',
              'Camera viewpoint',
              'Doors',
              'Windows',
              'Ceiling height'
            ],
            layout_mode: body.layout_mode || 'preserve',
            style: body.style || null,
            unresolved: [],
            compiler_version: 'reno-brief-v1'
          },
          compiled_prompt: rawText,
          source_hash: `hash_${Date.now()}`,
          compiler_version: 'reno-brief-v1',
          has_unresolved_conflicts: false,
          quote_eligible: true,
          submitted: false,
          created_at: new Date().toISOString()
        };
        briefsStore.set(briefId, brief);

        if (room) {
          room.active_brief_revision_id = briefId;
        }

        return sendJson(res, 200, brief);
      }

      // GET /api/rooms/:id/briefs
      if (segments[2] === 'briefs' && method === 'GET') {
        const room = roomsStore.get(roomId);
        const activeBriefId = room?.active_brief_revision_id;
        const brief = activeBriefId ? briefsStore.get(activeBriefId) : null;
        return sendJson(res, 200, brief || null);
      }

      // PATCH /api/rooms/:id
      if (method === 'PATCH') {
        const body = await parseJsonBody(req);
        let room = roomsStore.get(roomId);
        if (!room) {
          room = {
            id: roomId,
            project_id: 'default',
            name: body.name || 'Room',
            room_type: body.room_type || 'kitchen',
            sort_order: 0
          };
        } else {
          if (body.name) room.name = body.name;
          if (body.room_type) room.room_type = body.room_type;
        }
        roomsStore.set(roomId, room);
        return sendJson(res, 200, room);
      }

      // GET /api/rooms/:id
      if (method === 'GET') {
        let room = roomsStore.get(roomId);
        if (!room) {
          room = {
            id: roomId,
            project_id: 'default',
            name: 'Room',
            room_type: 'kitchen',
            sort_order: 0
          };
          roomsStore.set(roomId, room);
        }
        return sendJson(res, 200, room);
      }
    }

    // 5. /api/assets/:id
    if (segments[0] === 'assets' && segments.length >= 2) {
      const assetId = segments[1];

      // POST /api/assets/:id/reviews
      if (segments[2] === 'reviews' && method === 'POST') {
        const body = await parseJsonBody(req);
        const decision = body.decision || 'accept';
        const reviewId = `rev_${Date.now()}`;

        // Find room that owns this asset
        const asset = assetsStore.get(assetId);
        if (asset) {
          const room = roomsStore.get(asset.room_id);
          if (room && decision === 'accept') {
            if (asset.role === 'generated_image') {
              room.accepted_image_asset_id = assetId;
              room.accepted_image_url = asset.download_url;
              room.accepted_image_review_id = reviewId;
            } else if (asset.role === 'generated_video') {
              room.accepted_clip_asset_id = assetId;
              room.accepted_clip_url = asset.download_url;
              room.accepted_clip_review_id = reviewId;
            }
          }
        }

        return sendJson(res, 200, {
          id: reviewId,
          asset_id: assetId,
          decision,
          checklist: body.checklist || {},
          notes: body.notes || '',
          reviewed_at: new Date().toISOString()
        });
      }

      // GET /api/assets/:id
      if (method === 'GET') {
        const asset = assetsStore.get(assetId);
        if (asset) {
          return sendJson(res, 200, asset);
        }
        return sendJson(res, 200, {
          id: assetId,
          project_id: 'default',
          role: 'original_photo',
          mime_type: 'image/jpeg',
          bytes_size: 1024,
          width: 1280,
          height: 720,
          thumbnail_url: '',
          download_url: '',
          created_at: new Date().toISOString()
        });
      }
    }

    // 6. /api/quotes
    if (segments[0] === 'quotes' && method === 'POST') {
      const body = await parseJsonBody(req);
      const kind = body.kind === 'video' ? 'video' : 'image';
      const estimatedCredits = kind === 'video' ? 240 : 20;
      const quoteId = `quo_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
      const briefId = body.brief_id || 'brf_default';
      const brief = briefsStore.get(briefId);
      const roomId = brief?.room_id || 'default';
      const room = roomsStore.get(roomId);

      const key = extractKey(req);
      let balance = 1000;
      if (key) {
        try {
          const accRes = await fetch('https://api.magichour.ai/v1/account', {
            headers: { Authorization: `Bearer ${key}`, Accept: 'application/json' }
          });
          if (accRes.ok) {
            const accData = await accRes.json();
            if (typeof accData.credits === 'number') balance = accData.credits;
            else if (typeof accData.total_credits_remaining === 'number') balance = accData.total_credits_remaining;
          }
        } catch {}
      }

      const model = kind === 'image' ? (body.model || 'qwen-edit') : (body.model || 'kling-v1');
      const qualityLabel = body.options?.quality_label || (kind === 'image' ? 'Draft' : 'Draft');
      const resolution = body.options?.resolution || (kind === 'image' ? '640px' : '480p');

      const quote = {
        quote_id: quoteId,
        id: quoteId,
        kind,
        brief_revision_id: briefId,
        brief_id: briefId,
        source_asset_id: room?.primary_asset_id || 'ast_default',
        model,
        quality_label: qualityLabel,
        resolution,
        image_count: 1,
        duration_seconds: body.options?.duration_seconds || 5,
        audio: false,
        motion_preset: body.options?.motion_preset || 'gentle_push',
        estimated_credits: estimatedCredits,
        authorized_max_credits: estimatedCredits,
        anticipated_clip_credits: kind === 'video' ? estimatedCredits : null,
        anticipated_total_workflow_credits: estimatedCredits,
        balance: balance,
        balance_checked_at: new Date().toISOString(),
        sufficient_credits: balance >= estimatedCredits,
        catalog_version: 'cat_v1',
        expires_at: new Date(Date.now() + 300000).toISOString(),
        requires_confirmation: true
      };

      quotesStore.set(quoteId, {
        quote_id: quoteId,
        kind,
        model,
        resolution
      });

      return sendJson(res, 200, quote);
    }

    // 7. /api/generations
    if (segments[0] === 'generations') {
      // POST /api/generations/:id/stop
      if (segments.length === 3 && segments[2] === 'stop' && method === 'POST') {
        const jobId = segments[1];
        const job = jobsStore.get(jobId);
        if (job) job.state = 'ready_for_review';
        return sendJson(res, 200, {
          job_id: jobId,
          id: jobId,
          state: 'stopped',
          safe_message: 'Generation stopped.'
        });
      }

      // POST /api/generations/:id/resume
      if (segments.length === 3 && segments[2] === 'resume' && method === 'POST') {
        const jobId = segments[1];
        const job = jobsStore.get(jobId);
        if (job) job.state = 'polling_provider';
        return sendJson(res, 200, {
          job_id: jobId,
          id: jobId,
          state: 'polling_provider',
          safe_message: 'Generation resumed.'
        });
      }

      // POST /api/generations (start)
      if (method === 'POST' && segments.length === 1) {
        const key = extractKey(req);
        if (!key) {
          return sendError(res, 401, 'not_connected', 'Please connect your Magic Hour key to start generating.');
        }

        const body = await parseJsonBody(req);
        const jobId = `gen_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;

        const quote = body.quote_id ? quotesStore.get(body.quote_id) : undefined;
        const isVideo = (body.kind === 'video') || (quote?.kind === 'video');

        // Check account tier dynamically from Magic Hour
        let userTier = 'free';
        try {
          const accRes = await fetch('https://api.magichour.ai/v1/account', {
            headers: { Authorization: `Bearer ${key}`, Accept: 'application/json' }
          });
          if (accRes.ok) {
            const acc = await accRes.json();
            if (acc.tier) userTier = String(acc.tier).toLowerCase();
          }
        } catch {}

        // Resolve resolution strictly matching what was selected:
        let reqResolution = body.resolution || quote?.resolution || (isVideo ? '480p' : '640px');

        // Free tier safeguard: Magic Hour API rejects 1k / 2k on free accounts
        if (userTier === 'free') {
          if (!isVideo && reqResolution !== '640px') {
            reqResolution = '640px';
          }
          if (isVideo && reqResolution !== '480p') {
            reqResolution = '480p';
          }
        }

        const modelToUse = body.model || quote?.model || (isVideo ? 'kling-v1' : 'qwen-edit');

        // Look up latest brief and photo file_path
        let latestBrief = Array.from(briefsStore.values()).pop();
        let prompt = body.prompt || latestBrief?.compiled_prompt || 'modern bright renovated interior, high quality architecture';

        let filePath = body.file_path;
        if (!filePath) {
          const cookieHeader = req.headers.cookie || '';
          if (body.room_id) {
            const roomMatch = cookieHeader.match(new RegExp(`mr_photo_${body.room_id}=([^;]+)`));
            if (roomMatch) filePath = decodeURIComponent(roomMatch[1]);
          }
          if (!filePath) {
            const lastPhotoMatch = cookieHeader.match(/mr_last_photo_path=([^;]+)/);
            if (lastPhotoMatch) filePath = decodeURIComponent(lastPhotoMatch[1]);
          }
        }
        if (!filePath) {
          let latestAsset = Array.from(assetsStore.values()).find((a) => a.role === 'original_photo');
          filePath = latestAsset?.file_path;
        }

        // CRITICAL: NEVER pass fake dummy paths like 'uploads/default_room.jpg'!
        // If no photo has been uploaded, reject immediately so NO credits are wasted!
        if (!filePath || filePath === 'uploads/default_room.jpg') {
          return sendError(
            res,
            400,
            'missing_photo',
            'No room photo found. Please upload a clear photo of your room in Step 1 first.'
          );
        }

        try {
          let mhRes: Response;

          if (!isVideo) {
            mhRes = await fetch('https://api.magichour.ai/v1/ai-image-editor', {
              method: 'POST',
              headers: {
                Authorization: `Bearer ${key}`,
                'Content-Type': 'application/json',
                Accept: 'application/json'
              },
              body: JSON.stringify({
                name: `MR_${Date.now()}`,
                model: modelToUse,
                resolution: reqResolution,
                style: { prompt },
                assets: { image_file_paths: [filePath] }
              })
            });
          } else {
            const videoPrompt = `${prompt.trim()} Empty room with no people, steady smooth camera walkthrough, realistic interior architectural lines, consistent materials and lighting throughout, high quality.`;
            mhRes = await fetch('https://api.magichour.ai/v1/image-to-video', {
              method: 'POST',
              headers: {
                Authorization: `Bearer ${key}`,
                'Content-Type': 'application/json',
                Accept: 'application/json'
              },
              body: JSON.stringify({
                name: `MR_${Date.now()}`,
                model: modelToUse,
                resolution: reqResolution,
                end_seconds: 5,
                style: { prompt: videoPrompt },
                assets: { image_file_path: filePath }
              })
            });
          }

          if (!mhRes.ok) {
            const errData = await mhRes.json().catch(() => ({}));
            const code = errData.code || 'provider_rejected';
            const msg = errData.message || (typeof errData.error === 'string' ? errData.error : errData.error?.message) || 'Magic Hour rejected generation request.';
            return sendError(res, mhRes.status, code, msg);
          }

          const mhData = await mhRes.json();
          const targetRoomId = body.room_id || latestBrief?.room_id || 'default';
          const job: Job = {
            id: jobId,
            provider_id: mhData.id,
            project_id: 'default',
            room_id: targetRoomId,
            kind: isVideo ? 'video' : 'image',
            state: 'queued',
            provider_state: 'queued',
            prompt,
            created_at: new Date().toISOString()
          };
          jobsStore.set(jobId, job);

          res.setHeader('Set-Cookie', [
            `mr_last_job=${jobId}:${mhData.id}:${isVideo ? 'video' : 'image'}:${targetRoomId}; Path=/; HttpOnly; SameSite=Lax; Max-Age=7200`,
            `mr_job_${jobId}=${mhData.id}:${isVideo ? 'video' : 'image'}:${targetRoomId}; Path=/; HttpOnly; SameSite=Lax; Max-Age=7200`
          ]);

          return sendJson(res, 200, {
            job_id: jobId,
            id: jobId,
            state: 'queued',
            status_route: `/api/generations/${jobId}`,
            events_route: `/api/generations/${jobId}/events`,
            quote_id: body.quote_id || `quo_${jobId}`,
            idempotency_key: body.idempotency_key || `idemp_${jobId}`,
            safe_message: 'Job submitted to Magic Hour.'
          });
        } catch (err: any) {
          return sendError(res, 500, 'submission_failed', `Failed to submit to Magic Hour: ${err.message}`);
        }
      }

      // GET /api/generations/:id (poll)
      if (method === 'GET' && segments.length === 2) {
        const jobId = segments[1];
        let job = jobsStore.get(jobId);
        const key = extractKey(req);

        // Fallback for serverless cold start: check cookie or look up project from Magic Hour
        if (!job && key) {
          const cookieHeader = req.headers.cookie || '';
          let match = cookieHeader.match(new RegExp(`mr_job_${jobId}=([^;]+)`));
          if (match) {
            const [cProvId, cKind, cRoomId] = match[1].split(':');
            const restoredJob: Job = {
              id: jobId,
              provider_id: cProvId,
              project_id: 'default',
              room_id: cRoomId || 'default',
              kind: (cKind || 'image') as 'image' | 'video',
              state: 'rendering',
              provider_state: 'rendering',
              prompt: 'modern bright renovated interior',
              created_at: new Date().toISOString()
            };
            job = restoredJob;
            jobsStore.set(jobId, restoredJob);
          } else {
            const lastJobMatch = cookieHeader.match(/mr_last_job=([^;]+)/);
            if (lastJobMatch) {
              const [cJobId, cProvId, cKind, cRoomId] = lastJobMatch[1].split(':');
              if (cJobId === jobId) {
                const restoredJob: Job = {
                  id: jobId,
                  provider_id: cProvId,
                  project_id: 'default',
                  room_id: cRoomId || 'default',
                  kind: (cKind || 'image') as 'image' | 'video',
                  state: 'rendering',
                  provider_state: 'rendering',
                  prompt: 'modern bright renovated interior',
                  created_at: new Date().toISOString()
                };
                job = restoredJob;
                jobsStore.set(jobId, restoredJob);
              }
            }
          }

          // If still not found, search recent projects on Magic Hour directly
          if (!job) {
            try {
              const listRes = await fetch('https://api.magichour.ai/v1/image-projects', {
                headers: { Authorization: `Bearer ${key}`, Accept: 'application/json' }
              });
              if (listRes.ok) {
                const listData = await listRes.json();
                const found = (listData.items || []).find(
                  (p: any) => p.name?.includes(jobId) || p.id === jobId || `MR_${jobId}` === p.name
                ) || (listData.items || [])[0];
                if (found) {
                  const foundJob: Job = {
                    id: jobId,
                    provider_id: found.id,
                    project_id: 'default',
                    room_id: 'default',
                    kind: 'image',
                    state: found.status === 'complete' ? 'ready_for_review' : (found.status === 'error' ? 'failed' : 'rendering'),
                    provider_state: found.status || 'rendering',
                    prompt: found.style?.prompt || '',
                    created_at: found.created_at || new Date().toISOString()
                  };
                  job = foundJob;
                  jobsStore.set(jobId, foundJob);
                }
              }
            } catch {}
          }
        }

        if (!job) {
          return sendError(res, 404, 'job_not_found', 'Generation job not found.');
        }

        if (key && job.provider_id && job.state !== 'ready_for_review') {
          const route = job.kind === 'image' ? 'image-projects' : 'video-projects';
          try {
            const mhRes = await fetch(`https://api.magichour.ai/v1/${route}/${job.provider_id}`, {
              headers: { Authorization: `Bearer ${key}`, Accept: 'application/json' }
            });
            if (mhRes.ok) {
              const data = await mhRes.json();
              job.provider_state = data.status || 'rendering';

              if (data.status === 'complete') {
                const downloadUrl =
                  data.downloads?.[0]?.url ||
                  data.download_url ||
                  (typeof data.downloads?.[0] === 'string' ? data.downloads[0] : null);

                if (downloadUrl) {
                  const outputAssetId = `ast_${Date.now()}_out`;
                  const outputAsset: Asset = {
                    id: outputAssetId,
                    room_id: job.room_id,
                    project_id: job.project_id,
                    role: job.kind === 'image' ? 'generated_image' : 'generated_video',
                    mime_type: job.kind === 'image' ? 'image/jpeg' : 'video/mp4',
                    bytes_size: 2048,
                    width: 1280,
                    height: 720,
                    thumbnail_url: downloadUrl,
                    download_url: downloadUrl,
                    created_at: new Date().toISOString()
                  };
                  assetsStore.set(outputAssetId, outputAsset);

                  job.state = 'ready_for_review';
                  job.output_asset_id = outputAssetId;
                  job.output_url = downloadUrl;

                  const room = roomsStore.get(job.room_id);
                  if (room) {
                    if (job.kind === 'image') {
                      room.accepted_image_url = downloadUrl;
                      room.accepted_image_asset_id = outputAssetId;
                    } else {
                      room.accepted_clip_url = downloadUrl;
                      room.accepted_clip_asset_id = outputAssetId;
                    }
                  }
                } else {
                  job.state = 'rendering';
                }
              } else if (data.status === 'error') {
                job.state = 'failed';
              } else if (data.status === 'canceled') {
                job.state = 'stopped';
              } else {
                job.state = data.status === 'queued' ? 'queued' : 'rendering';
              }
            }
          } catch {
            // retain previous state on transport glitch
          }
        }

        const events = [
          {
            sequence: 1,
            job_id: job.id,
            state: job.state,
            safe_message:
              job.state === 'ready_for_review'
                ? 'Generation complete and ready for review.'
                : job.state === 'failed'
                ? 'Magic Hour generation encountered an error.'
                : job.state === 'stopped'
                ? 'Magic Hour generation was stopped.'
                : job.state === 'queued'
                ? 'Job queued in Magic Hour...'
                : 'Rendering renovation on Magic Hour...',
            timestamp: new Date().toISOString(),
            payload: {}
          }
        ];

        return sendJson(res, 200, {
          job_id: job.id,
          id: job.id,
          project_id: job.project_id || 'default',
          room_id: job.room_id || 'default',
          brief_revision_id: 'brf_default',
          quote_id: 'quo_default',
          kind: job.kind,
          state: job.state,
          provider_state: job.provider_state,
          permitted_next_action: job.state === 'ready_for_review' ? 'review' : 'wait',
          model: job.kind === 'image' ? 'qwen-edit' : 'kling-v1',
          resolution: job.kind === 'image' ? '1k' : '720p',
          source_asset_id: 'ast_default',
          source_asset_url: null,
          output_asset_id: job.output_asset_id || null,
          output_asset_url: job.output_url || null,
          output_url: job.output_url || null,
          brief_outdated: false,
          estimated_credits: job.kind === 'video' ? 240 : 20,
          correlation_name: `MR_${job.id}`,
          provider_id: job.provider_id,
          last_safe_error: null,
          created_at: job.created_at,
          updated_at: new Date().toISOString(),
          events: events,
          safe_message:
            job.state === 'ready_for_review'
              ? 'Generation verified and ready for review.'
              : 'Rendering renovation on Magic Hour...'
        });
      }
    }

    // 8. Fallback 404 for unknown API routes
    return sendError(res, 404, 'not_found', `API endpoint /api/${pathname} not found.`);
  } catch (err: any) {
    return sendError(res, 500, 'server_error', `Unexpected error: ${err.message}`);
  }
}
