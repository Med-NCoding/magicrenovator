import React, { useEffect, useState } from 'react';
import { apiClient, SafeAppClientError } from '../../api/client';
import {
  BriefRevisionResponse,
  GenerationAdmissionResponse,
  QuoteOptions,
  QuoteResponse,
  RoomSummary,
} from '../../api/types';
import { useAppContext } from '../../app/providers';

interface QuoteCardProps {
  kind: 'image' | 'video';
  room: RoomSummary;
  briefRevision: BriefRevisionResponse | null;
  hasUnsavedBrief?: boolean;
  onEnsureBriefSaved?: () => Promise<BriefRevisionResponse | null>;
  autoQuoteNonce?: number;
  onQuoteReady?: () => void;
  onJobStarted: (admission: GenerationAdmissionResponse, quote: QuoteResponse) => void;
}

export function QuoteCard({
  kind,
  room,
  briefRevision,
  hasUnsavedBrief = false,
  onEnsureBriefSaved,
  autoQuoteNonce = 0,
  onQuoteReady,
  onJobStarted,
}: QuoteCardProps) {
  const { connection, openConnectModal, refreshConnection } = useAppContext();
  const isFreeTier = connection?.tier === 'free';

  const [qualityLabel, setQualityLabel] = useState<'Draft' | 'Presentation'>(
    isFreeTier ? 'Draft' : 'Presentation'
  );
  const [resolution, setResolution] = useState<QuoteOptions['resolution']>(
    kind === 'image' ? (isFreeTier ? '640px' : '1k') : isFreeTier ? '480p' : '720p'
  );
  const [durationSeconds, setDurationSeconds] = useState<number>(5);
  const [motionPreset, setMotionPreset] = useState<'nearly_still' | 'gentle_push' | 'small_lateral'>(
    'gentle_push'
  );
  const [quote, setQuote] = useState<QuoteResponse | null>(null);
  const [loadingQuote, setLoadingQuote] = useState(false);
  const [submittingJob, setSubmittingJob] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isFreeTier) {
      setQualityLabel('Draft');
      if (kind === 'video' && resolution !== '480p') {
        setResolution('480p');
      } else if (kind === 'image' && (resolution === '2k' || resolution === '1k')) {
        setResolution('640px');
      }
    }
  }, [isFreeTier, kind]);

  // Clear stale quote when brief revision, room, or media kind changes
  useEffect(() => {
    setQuote((prev) => {
      if (prev && briefRevision && prev.brief_revision_id === briefRevision.id && prev.kind === kind) {
        return prev;
      }
      return null;
    });
    setError(null);
  }, [briefRevision?.id, room.id, room.primary_asset_id, room.accepted_image_asset_id, kind]);

  const hasPhotoSource =
    kind === 'image'
      ? Boolean(room.primary_asset_id)
      : Boolean(room.accepted_image_asset_id || room.primary_asset_id);

  const canRequestQuote =
    Boolean(connection?.connected) &&
    Boolean((briefRevision && !briefRevision.has_unresolved_conflicts) || hasUnsavedBrief) &&
    hasPhotoSource;

  const requestQuoteForBrief = async (targetBrief: BriefRevisionResponse | null) => {
    if (!connection?.connected) {
      openConnectModal();
      return;
    }
    setLoadingQuote(true);
    setError(null);
    try {
      let activeRev = targetBrief;
      if ((hasUnsavedBrief || !activeRev) && onEnsureBriefSaved) {
        const saved = await onEnsureBriefSaved();
        if (saved) {
          activeRev = saved;
        }
      }
      if (!activeRev) {
        setError('Please enter and save your renovation brief above first.');
        return;
      }
      const q = await apiClient.createQuote(activeRev.id, kind, null, {
        quality_label: qualityLabel,
        resolution,
        image_count: 1,
        duration_seconds: durationSeconds,
        audio: false,
        motion_preset: motionPreset,
        anticipate_video: true,
        allow_direct_video: true,
      });
      setQuote(q);
      onQuoteReady?.();
    } catch (err) {
      if (err instanceof SafeAppClientError) {
        setError(err.message);
      } else {
        setError('Could not calculate credit quote. Please try again.');
      }
    } finally {
      setLoadingQuote(false);
    }
  };

  const handleRequestQuote = async () => {
    await requestQuoteForBrief(briefRevision);
  };

  // Automatically calculate a fresh quote when a revision triggers autoQuoteNonce
  useEffect(() => {
    if (autoQuoteNonce > 0 && briefRevision && connection?.connected && hasPhotoSource) {
      void requestQuoteForBrief(briefRevision);
    }
  }, [autoQuoteNonce, briefRevision?.id, kind]);

  const handleConfirmSpend = async () => {
    if (!quote || submittingJob) return;
    setSubmittingJob(true);
    setError(null);
    try {
      const idempotencyKey = `idemp_${quote.quote_id}`;
      const admission = await apiClient.startGeneration(quote.quote_id, idempotencyKey);
      const confirmedQuote = quote;
      setQuote(null);
      onJobStarted(admission, confirmedQuote);
    } catch (err) {
      if (err instanceof SafeAppClientError) {
        setError(err.message);
      } else {
        setError('Could not start generation.');
      }
    } finally {
      setSubmittingJob(false);
    }
  };

  const showEstimateControls = !quote && !(autoQuoteNonce > 0 && loadingQuote);

  return (
    <section
      className="card"
      aria-labelledby={`quote-section-${kind}`}
      style={{ marginBottom: '20px' }}
      data-testid={`quote-card-${kind}`}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
        <div>
          <h3 id={`quote-section-${kind}`} style={{ margin: 0 }}>
            {quote
              ? kind === 'image'
                ? 'Ready to Run — Confirm Photo Generation'
                : 'Ready to Run — Confirm Video Clip Generation'
              : kind === 'image'
                ? '3. Photo Credit Quote & Generate'
                : '3. Video Clip Credit Quote & Generate'}
          </h3>
          <p className="field-helper" style={{ marginBottom: 0 }}>
            {quote
              ? 'Review your credit cost below and click Confirm & Spend to run it on Magic Hour.'
              : kind === 'image'
                ? 'Check your credit cost and generate your renovated room photo.'
                : 'Check your credit cost and generate your renovated room video clip.'}
          </p>
        </div>
        {connection?.tier && (
          <span className="badge badge-neutral">Account Tier: {connection.tier.toUpperCase()}</span>
        )}
      </div>

      {loadingQuote && !quote && (
        <div
          style={{
            marginTop: '14px',
            padding: '16px',
            borderRadius: '8px',
            background: 'var(--surface-subtle)',
            border: '1px solid var(--border)',
            fontWeight: 600,
          }}
          aria-live="polite"
        >
          Calculating your Magic Hour credit quote…
        </div>
      )}

      {showEstimateControls && (
        <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', marginTop: '14px', alignItems: 'flex-end' }}>
          <div>
            <label className="field-label" htmlFor={`quality-${kind}`}>
              Quality Preset
            </label>
            <select
              id={`quality-${kind}`}
              className="field-input"
              value={qualityLabel}
              onChange={(e) => {
                const next = e.target.value as 'Draft' | 'Presentation';
                setQualityLabel(next);
                setQuote(null);
              }}
            >
              <option value="Draft">
                Draft ({kind === 'image' ? 'qwen-edit' : 'ltx-2.5'})
              </option>
              <option value="Presentation" disabled={isFreeTier}>
                Presentation ({kind === 'image' ? 'seedream-v4.5' : 'kling-3.0'})
                {isFreeTier ? ' — Paid Tier Only' : ''}
              </option>
            </select>
          </div>

          <div>
            <label className="field-label" htmlFor={`resolution-${kind}`}>
              Resolution
            </label>
            {kind === 'image' ? (
              <select
                id={`resolution-${kind}`}
                className="field-input"
                value={resolution || '1k'}
                onChange={(e) => {
                  setResolution(e.target.value as QuoteOptions['resolution']);
                  setQuote(null);
                }}
              >
                <option value="640px">640px</option>
                <option value="1k">1k (Standard)</option>
                <option value="2k" disabled={isFreeTier}>
                  2k {isFreeTier ? '(Paid Tier)' : ''}
                </option>
              </select>
            ) : (
              <select
                id={`resolution-${kind}`}
                className="field-input"
                value={resolution || (isFreeTier ? '480p' : '720p')}
                onChange={(e) => {
                  setResolution(e.target.value as QuoteOptions['resolution']);
                  setQuote(null);
                }}
              >
                <option value="480p">480p</option>
                <option value="720p" disabled={isFreeTier}>
                  720p {isFreeTier ? '(Paid Tier)' : ''}
                </option>
                <option value="1080p" disabled={isFreeTier}>
                  1080p {isFreeTier ? '(Paid Tier)' : ''}
                </option>
              </select>
            )}
          </div>

          {kind === 'video' && (
            <>
              <div>
                <label className="field-label" htmlFor="video-motion-preset">
                  Camera Motion Preset
                </label>
                <select
                  id="video-motion-preset"
                  className="field-input"
                  value={motionPreset}
                  onChange={(e) => {
                    setMotionPreset(e.target.value as 'nearly_still' | 'gentle_push' | 'small_lateral');
                    setQuote(null);
                  }}
                >
                  <option value="gentle_push">Gentle Forward Push</option>
                  <option value="small_lateral">Small Lateral Glide</option>
                  <option value="nearly_still">Nearly Still Tripod</option>
                </select>
              </div>
              <div>
                <label className="field-label" htmlFor="video-duration">
                  Duration
                </label>
                <select
                  id="video-duration"
                  className="field-input"
                  value={durationSeconds}
                  onChange={(e) => {
                    setDurationSeconds(Number(e.target.value));
                    setQuote(null);
                  }}
                >
                  <option value={5}>5 seconds</option>
                  <option value={6}>6 seconds</option>
                  <option value={8}>8 seconds</option>
                </select>
              </div>
            </>
          )}

          <button
            type="button"
            className="btn btn-primary"
            disabled={!canRequestQuote || loadingQuote}
            onClick={handleRequestQuote}
            data-testid={`calculate-quote-${kind}`}
          >
            {loadingQuote ? 'Calculating Quote…' : 'Calculate Credit Quote'}
          </button>
        </div>
      )}

      {!connection?.connected && (
        <p className="field-helper" style={{ marginTop: '10px' }}>
          Connect your Magic Hour API key in the header before requesting a credit quote.
        </p>
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

      {quote && (
        <div
          style={{
            marginTop: '16px',
            padding: '16px',
            borderRadius: '8px',
            background: 'var(--surface-subtle)',
            border: '1px solid var(--border)',
          }}
          data-testid={`quote-summary-${kind}`}
        >
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
            <div>
              <span className="field-helper">Format &amp; Model</span>
              <div style={{ fontWeight: 600 }}>
                {kind === 'image' ? 'Photo' : 'Video Clip'} · {quote.quality_label} ({quote.model}) · {quote.resolution}
              </div>
            </div>
            <div>
              <span className="field-helper">Credits to Run</span>
              <div style={{ fontWeight: 700, fontSize: '1.15rem', color: 'var(--accent)' }} data-testid={`quote-credits-${kind}`}>
                {quote.estimated_credits} credits
              </div>
            </div>
            <div>
              <span className="field-helper">Your Balance</span>
              <div style={{ fontWeight: 600 }}>{quote.balance} credits</div>
            </div>
          </div>

          {!quote.sufficient_credits ? (
            <div
              role="alert"
              style={{
                marginTop: '12px',
                padding: '12px',
                borderRadius: '8px',
                background: '#FFFBEB',
                border: '1px solid #F59E0B',
                color: '#92400E',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '12px',
              }}
            >
              <span>
                Insufficient credits ({quote.balance} available, {quote.estimated_credits} required). Top up on Magic Hour and refresh your balance.
              </span>
              <div style={{ display: 'flex', gap: '8px' }}>
                <a
                  href="https://magichour.ai/pricing"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-secondary"
                >
                  Top Up Credits
                </a>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={async () => {
                    await refreshConnection();
                    await handleRequestQuote();
                  }}
                >
                  Refresh Balance &amp; Re-Quote
                </button>
              </div>
            </div>
          ) : (
            <div style={{ marginTop: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
              <span className="field-helper" style={{ margin: 0 }}>
                Authorize {quote.estimated_credits} credits from your Magic Hour account to run this now.
              </span>
              <button
                type="button"
                className="btn btn-primary"
                disabled={submittingJob}
                onClick={handleConfirmSpend}
                data-testid={`confirm-quote-${kind}`}
              >
                {submittingJob
                  ? 'Starting on Magic Hour…'
                  : `Confirm & Spend ${quote.estimated_credits} Credits — Run It`}
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
