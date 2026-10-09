import React from 'react';
import { GenerationSnapshotResponse } from '../../api/types';

export function JobProgress({
  job,
  onStop,
  onResume,
}: {
  job: GenerationSnapshotResponse | null;
  onStop?: () => Promise<void>;
  onResume?: (confirmNotInDashboard: boolean) => Promise<void>;
}) {
  if (!job) return null;

  return (
    <div className="card" aria-live="polite" style={{ marginTop: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0 }}>
          {job.kind === 'image' ? 'Concept Image' : 'Room Video Clip'} Status: {job.state}
        </h3>
        <span className="badge">{job.model} · {job.resolution}</span>
      </div>
      {job.brief_outdated && (
        <div className="alert alert-warning" style={{ marginTop: '12px' }}>
          Generated from an earlier brief revision (active brief has changed).
        </div>
      )}
      {job.state === 'submission_unknown' && (
        <div className="alert alert-warning" style={{ marginTop: '12px' }}>
          <p style={{ margin: '0 0 8px 0' }}>
            We could not confirm whether Magic Hour accepted this request. Check its status before trying again.
          </p>
          <p className="field-helper" style={{ margin: '0 0 12px 0' }}>
            Marker: <code>{job.correlation_name}</code> · Job ID: <code>{job.job_id}</code>
          </p>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <a
              href="https://magichour.ai/my-library"
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-secondary"
            >
              Check Magic Hour dashboard ↗
            </a>
            {onResume && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void onResume(true)}
              >
                I confirmed this request did not appear
              </button>
            )}
          </div>
        </div>
      )}
      {job.state === 'blocked_credits' && (
        <div className="alert alert-warning" style={{ marginTop: '12px' }}>
          <p style={{ margin: '0 0 8px 0' }}>
            You need more Magic Hour credits to create this video. Add credits in Magic Hour, then return and refresh your balance.
          </p>
          <a
            href="https://magichour.ai/pricing"
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-secondary"
          >
            Add credits ↗
          </a>
        </div>
      )}
      {onStop && !['accepted', 'rejected', 'failed', 'stopped', 'ready_for_review'].includes(job.state) && (
        <div style={{ marginTop: '12px' }}>
          <button type="button" className="btn btn-secondary" onClick={onStop}>
            Stop future app work
          </button>
        </div>
      )}
    </div>
  );
}
