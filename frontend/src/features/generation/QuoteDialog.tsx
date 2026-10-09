import React from 'react';
import { QuoteResponse } from '../../api/types';

export function QuoteDialog({
  quote,
  submitting,
  onConfirm,
  onCancel,
}: {
  quote: QuoteResponse | null;
  submitting: boolean;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}) {
  if (!quote) return null;

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="quote-dialog-title">
      <div className="modal-card">
        <h2 id="quote-dialog-title" style={{ marginTop: 0 }}>
          Confirm {quote.kind === 'image' ? 'Concept Image' : 'Room Video Clip'} Quote
        </h2>
        <p className="field-helper">
          Model: <strong>{quote.quality_label}</strong> ({quote.model}) · Resolution: <strong>{quote.resolution}</strong>
        </p>
        <div className="card" style={{ marginBottom: '16px', padding: '16px' }}>
          <p style={{ margin: '0 0 8px 0' }}>
            Estimated stage cost: <strong>{quote.estimated_credits} credits</strong>
          </p>
          {quote.anticipated_clip_credits != null && (
            <p style={{ margin: '0 0 8px 0', color: 'var(--text-muted)' }}>
              Anticipated later video clip estimate: {quote.anticipated_clip_credits} credits (separate confirmation required after image approval)
            </p>
          )}
          <p style={{ margin: 0 }}>
            Current Magic Hour balance: <strong>{quote.balance} credits</strong>
          </p>
        </div>

        {!quote.sufficient_credits && (
          <div className="alert alert-warning" role="alert">
            Add credits in Magic Hour, then return and refresh your balance.
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={submitting}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={onConfirm}
            disabled={submitting || !quote.sufficient_credits}
          >
            {submitting ? 'Submitting…' : `Confirm & Generate (${quote.estimated_credits} credits)`}
          </button>
        </div>
      </div>
    </div>
  );
}
