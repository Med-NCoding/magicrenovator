import React, { useState } from 'react';

export function CompareViewer({
  beforeUrl,
  afterUrl,
  briefOutdated = false,
}: {
  beforeUrl: string;
  afterUrl: string;
  briefOutdated?: boolean;
}) {
  const [sliderPos, setSliderPos] = useState(50);
  const [mode, setMode] = useState<'slider' | 'side_by_side'>('slider');

  return (
    <div className="card" style={{ marginTop: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
        <h3 style={{ margin: 0 }}>Before & After Concept Comparison</h3>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            type="button"
            className={`btn ${mode === 'slider' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setMode('slider')}
          >
            Slider View
          </button>
          <button
            type="button"
            className={`btn ${mode === 'side_by_side' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setMode('side_by_side')}
          >
            Side by Side
          </button>
        </div>
      </div>

      {briefOutdated && (
        <div className="alert alert-warning">
          This result was generated from an earlier brief revision. Your latest brief edits have not been generated yet.
        </div>
      )}

      {mode === 'slider' ? (
        <div>
          <div style={{ position: 'relative', width: '100%', height: '420px', overflow: 'hidden', borderRadius: '8px', background: '#1e1c1a' }}>
            <img
              src={afterUrl}
              alt="Renovated concept after"
              style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain' }}
            />
            <div
              style={{
                position: 'absolute',
                inset: 0,
                clipPath: `inset(0 ${100 - sliderPos}% 0 0)`,
              }}
            >
              <img
                src={beforeUrl}
                alt="Original room before"
                style={{ width: '100%', height: '100%', objectFit: 'contain' }}
              />
            </div>
          </div>
          <div style={{ marginTop: '12px' }}>
            <label htmlFor="compare-slider-range" className="field-label">
              Comparison split ({sliderPos}% original / {100 - sliderPos}% concept)
            </label>
            <input
              id="compare-slider-range"
              type="range"
              min={0}
              max={100}
              value={sliderPos}
              onChange={(e) => setSliderPos(Number(e.target.value))}
              style={{ width: '100%' }}
            />
          </div>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
          <div>
            <p className="field-label">Original Room Photo</p>
            <img src={beforeUrl} alt="Original room before" style={{ width: '100%', borderRadius: '8px' }} />
          </div>
          <div>
            <p className="field-label">Renovated Concept</p>
            <img src={afterUrl} alt="Renovated concept after" style={{ width: '100%', borderRadius: '8px' }} />
          </div>
        </div>
      )}
    </div>
  );
}
