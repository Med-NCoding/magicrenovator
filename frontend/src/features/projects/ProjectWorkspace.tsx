import React, { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { apiClient, SafeAppClientError } from '../../api/client';
import { useAppContext } from '../../app/providers';

const ACCEPTED_EXTENSIONS = new Set([
  'jpg',
  'jpeg',
  'png',
  'webp',
  'heic',
  'heif',
  'avif',
  'tiff',
  'tif',
  'bmp',
  'jfif',
]);

function triggerBrowserDownload(dataOrProxyUrl: string, rawRemoteUrl: string | null, filename: string) {
  try {
    if (dataOrProxyUrl.startsWith('data:')) {
      const parts = dataOrProxyUrl.split(',');
      const mimeMatch = parts[0].match(/:(.*?);/);
      const mime = mimeMatch ? mimeMatch[1] : 'image/jpeg';
      const bstr = atob(parts[1]);
      let n = bstr.length;
      const u8arr = new Uint8Array(n);
      while (n--) {
        u8arr[n] = bstr.charCodeAt(n);
      }
      const blob = new Blob([u8arr], { type: mime });
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(blobUrl), 5000);
      return;
    }
  } catch {
    // Fallback to server attachment stream below
  }

  const targetUrl = rawRemoteUrl || dataOrProxyUrl;
  const downloadHref = targetUrl.startsWith('http')
    ? `/api/proxy-image?url=${encodeURIComponent(targetUrl)}&download=1&filename=${encodeURIComponent(filename)}`
    : targetUrl;

  const a = document.createElement('a');
  a.href = downloadHref;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

export function ProjectWorkspace() {
  const { projectId, roomId } = useParams<{ projectId: string; roomId?: string }>();
  const workspaceId = projectId || roomId || 'default';
  const { connection, openConnectModal, setConnectionState } = useAppContext();

  const [projectName, setProjectName] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      const savedName = localStorage.getItem(`mr_project_name_${workspaceId}`);
      if (savedName) return savedName;
    }
    return 'Renovation Workspace';
  });

  // 1. Photo state (strictly isolated per project workspaceId — never reuse another project's photo)
  const [filePath, setFilePath] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(`mr_file_path_${workspaceId}`) || null;
  });
  const [originalPhotoUrl, setOriginalPhotoUrl] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null;
    const savedPath = localStorage.getItem(`mr_file_path_${workspaceId}`);
    if (!savedPath) return null;
    return localStorage.getItem(`mr_photo_preview_${workspaceId}`) || null;
  });
  const [uploadingPhoto, setUploadingPhoto] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // 2. Prompt & Generation Settings
  const [prompt, setPrompt] = useState<string>(() => {
    if (typeof window === 'undefined') return '';
    return localStorage.getItem(`mr_brief_prompt_${workspaceId}`) || '';
  });
  const [kind, setKind] = useState<'image' | 'video'>('image');
  const [resolution, setResolution] = useState<string>('640px');

  // 3. Active Generation & Result state
  const [activeJobId, setActiveJobId] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(`mr_active_job_${workspaceId}`) || null;
  });
  const [providerId, setProviderId] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null;
    const jId = localStorage.getItem(`mr_active_job_${workspaceId}`);
    return jId ? localStorage.getItem(`mr_provider_id_${jId}`) : null;
  });
  const [jobState, setJobState] = useState<string | null>(null);
  const [jobModel, setJobModel] = useState<string>('qwen-edit');
  const [jobResolution, setJobResolution] = useState<string>('640px');
  const [secondsElapsed, setSecondsElapsed] = useState<number>(0);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [genError, setGenError] = useState<string | null>(null);

  // 4. Output & Approval state
  const [outputDisplayUrl, setOutputDisplayUrl] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(`mr_output_data_${workspaceId}`) || localStorage.getItem(`mr_output_url_${workspaceId}`) || null;
  });
  const [outputRawUrl, setOutputRawUrl] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(`mr_output_url_${workspaceId}`) || null;
  });
  const [isApproved, setIsApproved] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    return localStorage.getItem(`mr_approved_${workspaceId}`) === '1';
  });
  const [downloadNotice, setDownloadNotice] = useState<string | null>(null);

  const resultSectionRef = useRef<HTMLDivElement>(null);

  // Reset and isolate state whenever switching to a different project workspaceId
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      localStorage.removeItem('mr_photo_preview_latest');
    } catch {}
    const savedName = localStorage.getItem(`mr_project_name_${workspaceId}`) || 'Renovation Workspace';
    const savedPath = localStorage.getItem(`mr_file_path_${workspaceId}`) || null;
    const savedPhoto = savedPath ? localStorage.getItem(`mr_photo_preview_${workspaceId}`) || null : null;
    const savedPrompt = localStorage.getItem(`mr_brief_prompt_${workspaceId}`) || '';
    const savedJobId = localStorage.getItem(`mr_active_job_${workspaceId}`) || null;
    const savedProviderId = savedJobId ? localStorage.getItem(`mr_provider_id_${savedJobId}`) : null;
    const savedOutData = localStorage.getItem(`mr_output_data_${workspaceId}`);
    const savedOutUrl = localStorage.getItem(`mr_output_url_${workspaceId}`);
    const savedApproved = localStorage.getItem(`mr_approved_${workspaceId}`) === '1';

    setProjectName(savedName);
    setFilePath(savedPath);
    setOriginalPhotoUrl(savedPhoto);
    setUploadingPhoto(false);
    setUploadError(null);
    setPrompt(savedPrompt);
    setActiveJobId(savedJobId);
    setProviderId(savedProviderId);
    setJobState(null);
    setGenError(null);
    setOutputDisplayUrl(savedOutData || savedOutUrl || null);
    setOutputRawUrl(savedOutUrl || null);
    setIsApproved(savedApproved);
    setDownloadNotice(null);
  }, [workspaceId]);

  // Load project title if available
  useEffect(() => {
    if (!workspaceId) return;
    apiClient
      .getProject(workspaceId)
      .then((proj) => {
        if (proj?.name && proj.name !== 'Renovation Project') {
          setProjectName(proj.name);
          try {
            localStorage.setItem(`mr_project_name_${workspaceId}`, proj.name);
          } catch {}
        }
      })
      .catch(() => {});
  }, [workspaceId]);

  // Keep resolution valid when switching between image and video
  useEffect(() => {
    if (kind === 'image' && !['640px', '1k', '2k'].includes(resolution)) {
      setResolution('640px');
    } else if (kind === 'video' && !['480p', '720p'].includes(resolution)) {
      setResolution('480p');
    }
  }, [kind, resolution]);

  // Elapsed timer while a job is queued or rendering
  const isJobRunning = jobState === 'queued' || jobState === 'rendering' || jobState === 'polling_provider';
  useEffect(() => {
    if (!isJobRunning) {
      setSecondsElapsed(0);
      return;
    }
    const start = Date.now();
    const timer = window.setInterval(() => {
      setSecondsElapsed(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [isJobRunning, activeJobId]);

  // Poll Magic Hour status when activeJobId is running
  useEffect(() => {
    if (!activeJobId || !isJobRunning) return;
    let active = true;
    let timeoutId: number | undefined;

    const poll = async () => {
      if (!active) return;
      try {
        const snap = await apiClient.getGeneration(activeJobId, {
          provider_id: providerId || undefined,
          kind,
          room_id: workspaceId,
          resolution: jobResolution,
          model: jobModel,
        });
        if (!active) return;

        setJobState(snap.state);
        if (snap.resolution) setJobResolution(snap.resolution);
        if (snap.model) setJobModel(snap.model);

        if (snap.state === 'ready_for_review') {
          const bestDisplay = snap.output_data_url || snap.output_asset_url || snap.output_url || null;
          const rawUrl = snap.output_url || snap.output_asset_url || bestDisplay;
          if (bestDisplay) {
            setOutputDisplayUrl(bestDisplay);
            setOutputRawUrl(rawUrl);
            try {
              if (rawUrl) localStorage.setItem(`mr_output_url_${workspaceId}`, rawUrl);
              if (snap.output_data_url) localStorage.setItem(`mr_output_data_${workspaceId}`, snap.output_data_url);
            } catch {}
          }
          apiClient
            .getConnectionStatus()
            .then((conn) => setConnectionState(conn))
            .catch(() => {});
          setTimeout(() => {
            resultSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }, 100);
          return;
        }

        if (snap.state === 'failed' || snap.state === 'stopped') {
          const errMsg =
            (snap.last_safe_error as any)?.message ||
            snap.events?.[0]?.safe_message ||
            'Magic Hour encountered an error processing this request.';
          setGenError(String(errMsg));
          return;
        }

        timeoutId = window.setTimeout(poll, 2500);
      } catch {
        if (active) {
          timeoutId = window.setTimeout(poll, 3500);
        }
      }
    };

    timeoutId = window.setTimeout(poll, 1500);
    return () => {
      active = false;
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [activeJobId, isJobRunning, providerId, kind, workspaceId, jobResolution, jobModel, setConnectionState]);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;

    setUploadError(null);
    setGenError(null);

    // Validate extension against Magic Hour's rules
    const extMatch = file.name.match(/\.([a-z0-9]+)$/i);
    const ext = extMatch ? extMatch[1].toLowerCase() : '';
    if (ext && !ACCEPTED_EXTENSIONS.has(ext)) {
      setUploadError(
        `File ".${ext}" is not accepted by Magic Hour. Supported image formats: JPG, JPEG, PNG, WebP, and HEIC.`
      );
      return;
    }

    if (
      file.type &&
      (file.type.includes('gif') ||
        file.type.includes('svg') ||
        file.type.includes('pdf') ||
        file.type.includes('video'))
    ) {
      setUploadError(
        `File type "${file.type}" is not accepted by Magic Hour. Please attach a JPG, JPEG, PNG, WebP, or HEIC photo.`
      );
      return;
    }

    if (file.size > 15 * 1024 * 1024) {
      setUploadError('Photo exceeds 15 MB limit. Please choose a smaller photo.');
      return;
    }

    if (!connection?.connected) {
      openConnectModal();
      setUploadError('Please connect your Magic Hour API key at the top right first.');
      return;
    }

    // Read local preview immediately so the user always sees their photo for this project
    const reader = new FileReader();
    reader.onload = (ev) => {
      const dataUrl = ev.target?.result as string;
      if (dataUrl) {
        setOriginalPhotoUrl(dataUrl);
        try {
          localStorage.setItem(`mr_photo_preview_${workspaceId}`, dataUrl);
        } catch {}
      }
    };
    reader.readAsDataURL(file);

    setUploadingPhoto(true);
    try {
      const uploaded = await apiClient.uploadRoomPhoto(workspaceId, file);
      if (uploaded?.file_path) {
        setFilePath(uploaded.file_path);
        try {
          localStorage.setItem(`mr_file_path_${workspaceId}`, uploaded.file_path);
        } catch {}
      }
      if (uploaded?.thumbnail_url && uploaded.thumbnail_url.startsWith('data:')) {
        setOriginalPhotoUrl(uploaded.thumbnail_url);
        try {
          localStorage.setItem(`mr_photo_preview_${workspaceId}`, uploaded.thumbnail_url);
        } catch {}
      }
    } catch (err) {
      setUploadError(
        err instanceof SafeAppClientError
          ? err.message
          : 'Failed to upload photo to Magic Hour. Please check your API key and try again.'
      );
    } finally {
      setUploadingPhoto(false);
    }
  };

  const isPaidTierResolution =
    (kind === 'image' && (resolution === '1k' || resolution === '2k')) ||
    (kind === 'video' && resolution === '720p');

  const estimatedCredits =
    kind === 'video'
      ? resolution === '480p'
        ? 120
        : 240
      : resolution === '640px'
      ? 10
      : resolution === '1k'
      ? 20
      : 40;

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting || isJobRunning) return;

    if (!connection?.connected) {
      openConnectModal();
      setGenError('Please connect your Magic Hour API key first.');
      return;
    }

    if (isPaidTierResolution) {
      setGenError(
        `You do not have the Magic Hour paid subscription tier, so ${resolution} resolution cannot be used. Please select ${
          kind === 'image' ? '640px (10 Credits)' : '480p (120 Credits)'
        } so you do not waste your credits.`
      );
      return;
    }

    if (!filePath) {
      setGenError('Please attach a photo in Step 1 first so Magic Hour has an image to edit.');
      return;
    }

    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt) {
      setGenError('Please enter a prompt describing how you want to renovate or edit the photo.');
      return;
    }

    setSubmitting(true);
    setGenError(null);
    setDownloadNotice(null);
    setIsApproved(false);
    try {
      localStorage.setItem(`mr_brief_prompt_${workspaceId}`, trimmedPrompt);
      localStorage.removeItem(`mr_approved_${workspaceId}`);
    } catch {}

    const chosenModel = kind === 'image' ? 'qwen-edit' : 'kling-v1';
    const chosenResolution = resolution;

    try {
      const quoteId = `quo_${Date.now()}`;
      const idempotencyKey = `idemp_${Date.now()}`;
      const admission = await apiClient.startGeneration(quoteId, idempotencyKey, {
        kind,
        resolution: chosenResolution,
        model: chosenModel,
        file_path: filePath,
        prompt: trimmedPrompt,
        room_id: workspaceId,
      });

      setActiveJobId(admission.job_id);
      setProviderId(admission.provider_id || null);
      setJobModel(chosenModel);
      setJobResolution(chosenResolution);
      setJobState('queued');

      try {
        localStorage.setItem(`mr_active_job_${workspaceId}`, admission.job_id);
        if (admission.provider_id) {
          localStorage.setItem(`mr_provider_id_${admission.job_id}`, admission.provider_id);
        }
        localStorage.setItem(`mr_resolution_${admission.job_id}`, chosenResolution);
        localStorage.setItem(`mr_model_${admission.job_id}`, chosenModel);
      } catch {}
    } catch (err) {
      setGenError(
        err instanceof SafeAppClientError
          ? err.message
          : 'Could not start Magic Hour generation. Please check your API key and credit balance.'
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleApproveAndDownload = () => {
    if (!outputDisplayUrl) return;
    setIsApproved(true);
    try {
      localStorage.setItem(`mr_approved_${workspaceId}`, '1');
    } catch {}

    const safeName = projectName.toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'renovation';
    const ext = kind === 'video' ? 'mp4' : 'jpg';
    const filename = `${safeName}-renovated.${ext}`;

    triggerBrowserDownload(outputDisplayUrl, outputRawUrl, filename);
    setDownloadNotice(`Approved! "${filename}" is downloading to your device.`);
  };

  return (
    <main style={{ maxWidth: '960px', margin: '0 auto', padding: '24px', width: '100%' }}>
      {/* Top Bar */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '12px',
          marginBottom: '20px',
        }}
      >
        <div>
          <Link
            to="/app"
            style={{ color: 'var(--text-muted)', textDecoration: 'none', fontSize: '0.9rem', fontWeight: 500 }}
          >
            &larr; Back to Projects
          </Link>
          <h1 style={{ margin: '4px 0 0 0', fontSize: '1.65rem' }}>{projectName}</h1>
        </div>
      </div>

      {/* STEP 1: Attach Photo */}
      <section className="card" style={{ marginBottom: '20px' }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '12px',
            marginBottom: '12px',
          }}
        >
          <div>
            <h2 style={{ margin: 0, fontSize: '1.2rem' }}>1. Attach Photo</h2>
            <p className="field-helper" style={{ margin: '4px 0 0 0' }}>
              Accepted by Magic Hour: <strong>JPG, JPEG, PNG, WebP, HEIC</strong> (up to 15 MB).
            </p>
          </div>
          <label
            className="btn btn-primary"
            style={{ cursor: uploadingPhoto ? 'wait' : 'pointer', display: 'inline-block' }}
          >
            {uploadingPhoto ? 'Uploading to Magic Hour…' : originalPhotoUrl ? 'Replace Photo' : 'Attach Photo'}
            <input
              type="file"
              accept=".jpg,.jpeg,.png,.webp,.heic,.heif,image/jpeg,image/png,image/webp,image/heic"
              onChange={handleFileChange}
              disabled={uploadingPhoto}
              style={{ display: 'none' }}
              data-testid="room-photo-input"
            />
          </label>
        </div>

        {uploadError && (
          <div className="alert alert-error" role="alert" style={{ marginBottom: '12px' }}>
            {uploadError}
          </div>
        )}

        {filePath && !uploadingPhoto && !uploadError && (
          <div style={{ marginBottom: '12px' }}>
            <span className="badge badge-connected">
              &#10003; Photo accepted &amp; uploaded to Magic Hour
            </span>
          </div>
        )}

        {originalPhotoUrl && (
          <div style={{ marginTop: '8px' }}>
            <img
              src={originalPhotoUrl}
              alt="Attached original"
              style={{
                maxWidth: '100%',
                maxHeight: '380px',
                objectFit: 'contain',
                borderRadius: '8px',
                border: '1px solid var(--border)',
                background: '#1c1917',
                display: 'block',
              }}
            />
          </div>
        )}
      </section>

      {/* STEP 2: Prompt & Generate */}
      <section className="card" style={{ marginBottom: '20px' }}>
        <h2 style={{ margin: '0 0 12px 0', fontSize: '1.2rem' }}>2. Renovation Prompt &amp; Generate</h2>
        <form onSubmit={handleGenerate}>
          <div style={{ marginBottom: '14px' }}>
            <label htmlFor="renovation-prompt" className="field-label">
              Describe your renovation or edit
            </label>
            <textarea
              id="renovation-prompt"
              className="textarea-input"
              rows={3}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g., Modern dorm room with warm oak desk, cozy warm lighting, clean white walls, and indoor plants"
              required
            />
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
              gap: '14px',
              marginBottom: '16px',
            }}
          >
            <div>
              <label htmlFor="output-format" className="field-label">
                Output Type
              </label>
              <select
                id="output-format"
                className="select-input"
                value={kind}
                onChange={(e) => setKind(e.target.value as 'image' | 'video')}
                disabled={isJobRunning}
              >
                <option value="image">Photo (Still Image · qwen-edit)</option>
                <option value="video">Video Walkthrough (5s Clip · kling-v1)</option>
              </select>
            </div>

            <div>
              <label htmlFor="output-resolution" className="field-label">
                Resolution &amp; Credit Cost
              </label>
              {kind === 'image' ? (
                <select
                  id="output-resolution"
                  className="select-input"
                  value={resolution}
                  onChange={(e) => {
                    setResolution(e.target.value);
                    setGenError(null);
                  }}
                  disabled={isJobRunning}
                >
                  <option value="640px">640px (10 Credits &mdash; Free &amp; Paid Tier)</option>
                  <option value="1k">1k (20 Credits &mdash; Paid Tier Only)</option>
                  <option value="2k">2k (40 Credits &mdash; Paid Tier Only)</option>
                </select>
              ) : (
                <select
                  id="output-resolution"
                  className="select-input"
                  value={resolution}
                  onChange={(e) => {
                    setResolution(e.target.value);
                    setGenError(null);
                  }}
                  disabled={isJobRunning}
                >
                  <option value="480p">480p (120 Credits &mdash; Free &amp; Paid Tier)</option>
                  <option value="720p">720p (240 Credits &mdash; Paid Tier Only)</option>
                </select>
              )}
            </div>
          </div>

          {isPaidTierResolution && (
            <div className="alert alert-error" role="alert" style={{ marginBottom: '14px' }}>
              <strong>Paid Tier Required:</strong> You do not have the Magic Hour paid subscription tier, so{' '}
              <strong>{resolution}</strong> resolution cannot be used. Please select{' '}
              <strong>{kind === 'image' ? '640px (10 Credits)' : '480p (120 Credits)'}</strong> so you don&apos;t waste
              your credits.
            </div>
          )}

          {genError && !isPaidTierResolution && (
            <div className="alert alert-error" role="alert" style={{ marginBottom: '14px' }}>
              {genError}
            </div>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting || isJobRunning || uploadingPhoto}
              data-testid="generate-btn"
            >
              {submitting
                ? 'Sending to Magic Hour…'
                : isJobRunning
                ? `Generating on Magic Hour (${secondsElapsed}s)…`
                : `Generate with Magic Hour (${estimatedCredits} Credits)`}
            </button>
            <span className="field-helper" style={{ margin: 0 }}>
              Model: <code>{kind === 'image' ? 'qwen-edit' : 'kling-v1'}</code> &middot; Resolution:{' '}
              <code>{resolution}</code>
            </span>
          </div>
        </form>
      </section>

      {/* STEP 3: Live Progress Indicator while running */}
      {isJobRunning && (
        <section className="card" style={{ marginBottom: '20px' }} aria-live="polite">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
            <div>
              <h3 style={{ margin: 0 }}>Generating Your Renovation on Magic Hour…</h3>
              <p className="field-helper" style={{ margin: '4px 0 0 0' }}>
                Model: <code>{jobModel}</code> &middot; Resolution: <code>{jobResolution}</code> &middot; Elapsed:{' '}
                <strong>{secondsElapsed}s</strong> (typically takes 15–35 seconds)
              </p>
            </div>
            <span className="badge badge-neutral">State: {jobState}</span>
          </div>
        </section>
      )}

      {/* STEP 4: Generated Result & One-Click Approve + Automatic Download */}
      {outputDisplayUrl && (
        <section ref={resultSectionRef} className="card" style={{ marginBottom: '24px' }} data-testid="result-section">
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: '12px',
              marginBottom: '16px',
            }}
          >
            <div>
              <h2 style={{ margin: 0, fontSize: '1.25rem' }}>3. Your Renovated Result ({projectName})</h2>
              <p className="field-helper" style={{ margin: '4px 0 0 0' }}>
                Model: <code>{jobModel}</code> &middot; Resolution: <code>{jobResolution}</code>
              </p>
            </div>
            {isApproved && (
              <span className="badge badge-connected" data-testid="approved-badge">
                &#10003; Approved &amp; Downloaded
              </span>
            )}
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
              gap: '16px',
              marginBottom: '20px',
            }}
          >
            {originalPhotoUrl && (
              <figure style={{ margin: 0 }}>
                <figcaption className="field-helper" style={{ fontWeight: 600, marginBottom: '6px' }}>
                  Original Photo
                </figcaption>
                <img
                  src={originalPhotoUrl}
                  alt="Original"
                  style={{
                    width: '100%',
                    maxHeight: '480px',
                    objectFit: 'contain',
                    borderRadius: '8px',
                    border: '1px solid var(--border)',
                    background: '#1c1917',
                    display: 'block',
                  }}
                />
              </figure>
            )}

            <figure style={{ margin: 0 }}>
              <figcaption className="field-helper" style={{ fontWeight: 600, marginBottom: '6px' }}>
                Renovated Result
              </figcaption>
              {kind === 'video' || outputDisplayUrl.endsWith('.mp4') ? (
                <video
                  key={outputDisplayUrl}
                  src={outputDisplayUrl}
                  controls
                  autoPlay
                  loop
                  style={{
                    width: '100%',
                    maxHeight: '480px',
                    borderRadius: '8px',
                    border: '1px solid var(--border)',
                    background: '#1c1917',
                    display: 'block',
                  }}
                />
              ) : (
                <img
                  key={outputDisplayUrl}
                  src={outputDisplayUrl}
                  alt="Renovated Result"
                  style={{
                    width: '100%',
                    maxHeight: '480px',
                    objectFit: 'contain',
                    borderRadius: '8px',
                    border: '1px solid var(--border)',
                    background: '#1c1917',
                    display: 'block',
                  }}
                  onError={(e) => {
                    const target = e.currentTarget;
                    const fallbackSource = outputRawUrl || outputDisplayUrl;
                    if (!target.dataset.proxyTried && fallbackSource && fallbackSource.startsWith('http')) {
                      target.dataset.proxyTried = 'true';
                      target.src = `/api/proxy-image?url=${encodeURIComponent(fallbackSource)}`;
                    }
                  }}
                />
              )}
            </figure>
          </div>

          {downloadNotice && (
            <div className="alert alert-success" role="status" style={{ marginBottom: '14px' }}>
              <strong>{downloadNotice}</strong>
            </div>
          )}

          <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleApproveAndDownload}
              data-testid="approve-download-btn"
            >
              &#10003; {isApproved ? 'Download Renovated Picture Again' : 'Approve & Automatically Download Picture'}
            </button>
          </div>
        </section>
      )}
    </main>
  );
}
