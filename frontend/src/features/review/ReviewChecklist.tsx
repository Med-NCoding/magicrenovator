import React, { useState } from 'react';
import { apiClient, SafeAppClientError } from '../../api/client';
import { ReviewChecklistPayload, ReviewResponse } from '../../api/types';

interface ReviewChecklistProps {
  assetId: string;
  kind: 'image' | 'video';
  onReviewed: (review: ReviewResponse) => void;
}

export function ReviewChecklist({ assetId, kind, onReviewed }: ReviewChecklistProps) {
  const [checklist, setChecklist] = useState<ReviewChecklistPayload>({
    room_shape_preserved: true,
    doors_windows_preserved: true,
    fixtures_preserved: true,
    materials_colors_accurate: true,
    no_unwanted_additions: true,
    no_visible_distortions: true,
    temporal_stability: kind === 'video' ? true : null,
    no_bent_edges_or_moving_cabinets: kind === 'video' ? true : null,
    no_impossible_extensions: kind === 'video' ? true : null,
    camera_movement_suitable: kind === 'video' ? true : null,
  });
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = (key: keyof ReviewChecklistPayload) => {
    setChecklist((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  const handleDecision = async (decision: 'accept' | 'revise' | 'reject') => {
    if (decision === 'revise' && !notes.trim()) {
      setError('Please write down your revised prompt before clicking Send Revision & Recalculate Quote.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await apiClient.submitReview(assetId, decision, checklist, notes.trim() || undefined);
      if (decision === 'revise') {
        setNotes('');
      }
      onReviewed(res);
    } catch (err) {
      if (err instanceof SafeAppClientError) {
        setError(err.message);
      } else {
        setError('Could not save review decision. Please try again.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      style={{
        marginTop: '16px',
        padding: '16px',
        borderRadius: '8px',
        background: 'var(--surface-subtle)',
        border: '1px solid var(--border)',
      }}
      data-testid={`review-checklist-${kind}`}
    >
      <h4 style={{ margin: '0 0 6px' }}>
        {kind === 'image' ? '4. Review Your Renovated Photo' : '4. Review Your Renovated Video Clip'}
      </h4>
      <p className="field-helper" style={{ marginTop: 0 }}>
        Approve the result to unlock your download below, or enter a revision below to recalculate your credit quote and have Magic Hour edit it.
      </p>

      <div style={{ marginTop: '12px' }}>
        <label className="field-label" htmlFor={`review-notes-${kind}`}>
          Need changes? Describe your revision for Magic Hour:
        </label>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <input
            id={`review-notes-${kind}`}
            data-testid={`review-notes-${kind}`}
            type="text"
            className="text-input"
            style={{ flex: '1 1 260px' }}
            placeholder="e.g., Remove the yellow light rays, make the oak floor warmer, keep everything else…"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <button
            type="button"
            className="btn btn-secondary"
            disabled={submitting || !notes.trim()}
            onClick={() => handleDecision('revise')}
            data-testid={`revise-review-${kind}`}
          >
            {submitting ? 'Saving Revision…' : 'Send Revision & Recalculate Quote'}
          </button>
        </div>
      </div>

      <details style={{ marginTop: '12px', fontSize: '0.875rem', color: 'var(--text-muted)' }}>
        <summary style={{ cursor: 'pointer', fontWeight: 500 }}>Optional verification checklist</summary>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '8px', marginTop: '8px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input
              type="checkbox"
              checked={checklist.room_shape_preserved}
              onChange={() => toggle('room_shape_preserved')}
            />
            Room shape &amp; footprint preserved
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input
              type="checkbox"
              checked={checklist.doors_windows_preserved}
              onChange={() => toggle('doors_windows_preserved')}
            />
            Doors &amp; windows preserved
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input
              type="checkbox"
              checked={checklist.fixtures_preserved}
              onChange={() => toggle('fixtures_preserved')}
            />
            Key fixtures preserved
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input
              type="checkbox"
              checked={checklist.materials_colors_accurate}
              onChange={() => toggle('materials_colors_accurate')}
            />
            Requested finishes &amp; colors match brief
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input
              type="checkbox"
              checked={checklist.no_unwanted_additions}
              onChange={() => toggle('no_unwanted_additions')}
            />
            No unrequested structural additions
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input
              type="checkbox"
              checked={checklist.no_visible_distortions}
              onChange={() => toggle('no_visible_distortions')}
            />
            Straight vertical lines &amp; unwarped geometry
          </label>

          {kind === 'video' && (
            <>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  type="checkbox"
                  checked={Boolean(checklist.temporal_stability)}
                  onChange={() => toggle('temporal_stability')}
                />
                Temporal stability across frames
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  type="checkbox"
                  checked={Boolean(checklist.no_bent_edges_or_moving_cabinets)}
                  onChange={() => toggle('no_bent_edges_or_moving_cabinets')}
                />
                No bent edges or drifting cabinets
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  type="checkbox"
                  checked={Boolean(checklist.no_impossible_extensions)}
                  onChange={() => toggle('no_impossible_extensions')}
                />
                No impossible room extensions
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  type="checkbox"
                  checked={Boolean(checklist.camera_movement_suitable)}
                  onChange={() => toggle('camera_movement_suitable')}
                />
                Smooth camera movement
              </label>
            </>
          )}
        </div>
      </details>

      {error && (
        <div
          role="alert"
          style={{
            marginTop: '12px',
            padding: '10px',
            borderRadius: '8px',
            background: '#FEF2F2',
            border: '1px solid #FCA5A5',
            color: 'var(--danger)',
          }}
        >
          {error}
        </div>
      )}

      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginTop: '14px' }}>
        <button
          type="button"
          className="btn btn-primary"
          disabled={submitting}
          onClick={() => handleDecision('accept')}
          data-testid={`accept-review-${kind}`}
        >
          {kind === 'image' ? 'Approve Photo & Unlock Download / Video' : 'Approve Video Clip & Unlock Download'}
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          disabled={submitting}
          onClick={() => handleDecision('reject')}
          data-testid={`reject-review-${kind}`}
        >
          Reject Output
        </button>
      </div>
    </div>
  );
}
