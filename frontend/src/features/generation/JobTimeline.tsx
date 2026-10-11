import React, { useEffect, useState } from 'react';
import { apiClient, SafeAppClientError } from '../../api/client';
import { GenerationSnapshotResponse } from '../../api/types';

interface JobTimelineProps {
  jobId: string;
  onJobUpdated: (snapshot: GenerationSnapshotResponse) => void;
}

const ACTIVE_STATES = new Set([
  'admitted',
  'preparing',
  'submitting',
  'queued',
  'rendering',
  'saving_output',
  'polling_provider',
]);

export function JobTimeline({ jobId, onJobUpdated }: JobTimelineProps) {
  const [snapshot, setSnapshot] = useState<GenerationSnapshotResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmNotInDashboard, setConfirmNotInDashboard] = useState(false);
  const [busy, setBusy] = useState(false);

  const fetchSnapshot = async () => {
    try {
      const snap = await apiClient.getGeneration(jobId);
      setSnapshot(snap);
      onJobUpdated(snap);
      return snap;
    } catch (err) {
      if (err instanceof SafeAppClientError) {
        setError(err.message);
      }
      return null;
    }
  };

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    let consecutiveErrors = 0;

    const pollLoop = async () => {
      if (!active) return;
      const snap = await fetchSnapshot();
      if (!active) return;
      if (snap) {
        consecutiveErrors = 0;
        if (ACTIVE_STATES.has(snap.state)) {
          timer = window.setTimeout(pollLoop, 1500);
        }
      } else {
        consecutiveErrors++;
        if (consecutiveErrors <= 5) {
          timer = window.setTimeout(pollLoop, 2000);
        }
      }
    };

    pollLoop();
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [jobId]);

  const handleStop = async () => {
    setBusy(true);
    setError(null);
    try {
      const updated = await apiClient.stopGeneration(jobId);
      setSnapshot(updated);
      onJobUpdated(updated);
    } catch (err) {
      if (err instanceof SafeAppClientError) setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const handleResume = async () => {
    setBusy(true);
    setError(null);
    try {
      const updated = await apiClient.resumeGeneration(jobId, {
        confirm_not_in_dashboard: confirmNotInDashboard,
        quote_id: snapshot?.quote_id || null,
      });
      setSnapshot(updated);
      onJobUpdated(updated);
    } catch (err) {
      if (err instanceof SafeAppClientError) setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (!snapshot) {
    return (
      <section className="card" style={{ marginBottom: '20px' }}>
        <p className="field-helper">Loading generation job status…</p>
      </section>
    );
  }

  return (
    <section
      className="card"
      aria-labelledby="job-timeline-title"
      style={{ marginBottom: '20px' }}
      data-testid="job-timeline"
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
        <div>
          <h3 id="job-timeline-title" style={{ margin: 0 }}>
            Generation Progress ({snapshot.kind === 'image' ? 'Renovated Still Image' : 'Room Video Clip'})
          </h3>
          <p className="field-helper" style={{ marginBottom: 0 }}>
            Model: <code>{snapshot.model}</code> · Resolution: <code>{snapshot.resolution}</code> · Correlation:{' '}
            <code>{snapshot.correlation_name}</code>
          </p>
        </div>
        <span
          className={`badge ${
            snapshot.state === 'ready_for_review' || snapshot.state === 'accepted'
              ? 'badge-ok'
              : snapshot.state === 'failed' || snapshot.state === 'submission_unknown'
              ? 'badge-warn'
              : 'badge-neutral'
          }`}
          data-testid="job-state-badge"
        >
          State: {snapshot.state}
        </span>
      </div>

      {snapshot.brief_outdated && (
        <div
          role="status"
          style={{
            marginTop: '12px',
            padding: '10px 12px',
            borderRadius: '8px',
            background: '#FFFBEB',
            border: '1px solid #FCD34D',
            color: '#92400E',
            fontSize: '0.875rem',
          }}
        >
          Note: The room renovation brief was updated after this job was created. This output reflects the earlier brief revision.
        </div>
      )}

      {snapshot.state === 'submission_unknown' && (
        <div
          role="alert"
          data-testid="submission-unknown-banner"
          style={{
            marginTop: '12px',
            padding: '14px',
            borderRadius: '8px',
            background: '#FFFBEB',
            border: '1px solid #F59E0B',
            color: '#92400E',
          }}
        >
          <strong>Ambiguous Provider Submission — Automatic Replay Blocked</strong>
          <p style={{ margin: '6px 0' }}>
            The network call to Magic Hour did not return a clear confirmation for correlation name{' '}
            <code>{snapshot.correlation_name}</code>. To protect your credits, magicrenovator never automatically re-submits paid requests.
          </p>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.875rem', marginTop: '8px' }}>
            <input
              type="checkbox"
              checked={confirmNotInDashboard}
              onChange={(e) => setConfirmNotInDashboard(e.target.checked)}
            />
            I checked my Magic Hour dashboard and confirmed no job with correlation <code>{snapshot.correlation_name}</code> was created.
          </label>
          <div style={{ marginTop: '10px' }}>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={!confirmNotInDashboard || busy}
              onClick={handleResume}
            >
              Close Ambiguous Attempt Safely
            </button>
          </div>
        </div>
      )}

      {snapshot.last_safe_error && (
        <div
          role="alert"
          style={{
            marginTop: '12px',
            padding: '12px',
            borderRadius: '8px',
            background: '#FEF2F2',
            border: '1px solid #FCA5A5',
            color: 'var(--danger)',
          }}
        >
          {String(snapshot.last_safe_error.message || 'An error occurred during generation.')}
        </div>
      )}

      {error && (
        <div
          role="alert"
          style={{
            marginTop: '12px',
            padding: '12px',
            borderRadius: '8px',
            background: '#FEF2F2',
            border: '1px solid #FCA5A5',
            color: 'var(--danger)',
          }}
        >
          {error}
        </div>
      )}

      <div style={{ marginTop: '14px' }}>
        <strong style={{ fontSize: '0.875rem' }}>Durable Event Log</strong>
        <ol
          style={{
            margin: '8px 0 0',
            paddingLeft: '20px',
            fontSize: '0.85rem',
            color: 'var(--text-muted)',
            display: 'grid',
            gap: '4px',
          }}
        >
          {snapshot.events.map((ev) => (
            <li key={ev.sequence}>
              <strong>[{ev.state}]</strong> {ev.safe_message}
            </li>
          ))}
        </ol>
      </div>

      <div style={{ marginTop: '14px', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
        {ACTIVE_STATES.has(snapshot.state) && (
          <button type="button" className="btn btn-secondary" disabled={busy} onClick={handleStop}>
            Stop Local Polling
          </button>
        )}
        {(snapshot.state === 'waiting_for_key' ||
          snapshot.state === 'blocked_credits' ||
          (snapshot.state === 'failed' && snapshot.provider_id && !snapshot.output_asset_id)) && (
          <button type="button" className="btn btn-primary" disabled={busy} onClick={handleResume}>
            {snapshot.state === 'failed'
              ? 'Retry Saving Output (No Extra Credits)'
              : 'Resume Generation'}
          </button>
        )}
      </div>
    </section>
  );
}
