import React, { useState } from 'react';
import { ReviewResponse } from '../../api/types';
import { ReviewChecklist } from './ReviewChecklist';

interface VideoReviewProps {
  clipAssetId: string;
  clipUrl: string;
  approvedStillUrl: string | null;
  roomName: string;
  isAccepted: boolean;
  canReview?: boolean;
  onReviewed: (review: ReviewResponse) => void;
  onQuickRevise?: (notes: string, kind: 'image' | 'video', referenceAssetId?: string) => Promise<void>;
}

export function VideoReview({
  clipAssetId,
  clipUrl,
  approvedStillUrl,
  roomName,
  isAccepted,
  canReview = false,
  onReviewed,
  onQuickRevise,
}: VideoReviewProps) {
  const [quickNotes, setQuickNotes] = useState('');
  const [revising, setRevising] = useState(false);

  const handleQuickRevise = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!onQuickRevise || !quickNotes.trim() || revising) return;
    setRevising(true);
    try {
      await onQuickRevise(quickNotes.trim(), 'video');
      setQuickNotes('');
    } finally {
      setRevising(false);
    }
  };

  return (
    <section
      className="card"
      aria-labelledby="video-review-title"
      style={{ marginBottom: '20px' }}
      data-testid="video-review-section"
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
        <h3 id="video-review-title" style={{ margin: 0 }}>
          Renovated Room Video Clip ({roomName})
        </h3>
        {isAccepted && (
          <span className="badge badge-connected" data-testid="video-accepted-badge">
            Video Approved — Ready to Download Below
          </span>
        )}
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: '16px',
          marginTop: '14px',
        }}
      >
        <div>
          <span className="field-helper" style={{ fontWeight: 600, display: 'block', marginBottom: '6px' }}>
            Generated Room Clip (MP4)
          </span>
          <video
            src={clipUrl}
            controls
            playsInline
            style={{ width: '100%', borderRadius: '8px', border: '1px solid var(--border)', background: '#000' }}
            data-testid="room-video-player"
          />
        </div>
        {approvedStillUrl && (
          <div>
            <span className="field-helper" style={{ fontWeight: 600, display: 'block', marginBottom: '6px' }}>
              Reference Photo
            </span>
            <img
              src={approvedStillUrl}
              alt={`Approved ${roomName} still concept`}
              style={{ width: '100%', borderRadius: '8px', border: '1px solid var(--border)' }}
            />
          </div>
        )}
      </div>

      {canReview ? (
        <ReviewChecklist assetId={clipAssetId} kind="video" onReviewed={onReviewed} />
      ) : (
        onQuickRevise && (
          <form
            onSubmit={handleQuickRevise}
            style={{
              marginTop: '14px',
              padding: '12px',
              borderRadius: '8px',
              background: 'var(--surface-subtle)',
              border: '1px solid var(--border)',
              display: 'flex',
              gap: '8px',
              flexWrap: 'wrap',
              alignItems: 'center',
            }}
          >
            <input
              type="text"
              className="text-input"
              style={{ flex: '1 1 240px' }}
              placeholder="Want to revise this video clip? Enter changes and recalculate quote…"
              value={quickNotes}
              onChange={(e) => setQuickNotes(e.target.value)}
            />
            <button type="submit" className="btn btn-secondary" disabled={revising || !quickNotes.trim()}>
              {revising ? 'Recalculating…' : 'Send Revision & Recalculate Quote'}
            </button>
          </form>
        )
      )}
    </section>
  );
}
