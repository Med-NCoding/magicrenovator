import React from 'react';

interface ImageCompareProps {
  beforeUrl: string;
  afterUrl: string;
  roomName: string;
}

export function ImageCompare({ beforeUrl, afterUrl, roomName }: ImageCompareProps) {
  return (
    <div style={{ marginTop: '14px' }} data-testid="image-compare">
      <div style={{ marginBottom: '10px' }}>
        <strong>Before / After Concept Comparison ({roomName})</strong>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px' }}>
        <figure style={{ margin: 0 }}>
          <figcaption className="field-helper" style={{ fontWeight: 600, marginBottom: '6px' }}>
            Original Room Photo
          </figcaption>
          {beforeUrl ? (
            <img
              key={beforeUrl}
              src={beforeUrl}
              alt={`Original ${roomName}`}
              loading="eager"
              style={{
                width: '100%',
                maxHeight: '480px',
                objectFit: 'contain',
                borderRadius: '8px',
                border: '1px solid var(--border)',
                background: '#1c1917',
                display: 'block'
              }}
              onError={(e) => {
                const target = e.currentTarget;
                if (!target.dataset.fallbackTried && typeof window !== 'undefined') {
                  target.dataset.fallbackTried = 'true';
                  const stored = localStorage.getItem('mr_photo_preview_latest');
                  if (stored && stored !== target.src) {
                    target.src = stored;
                  }
                }
              }}
            />
          ) : (
            <div
              style={{
                width: '100%',
                height: '240px',
                borderRadius: '8px',
                border: '1px dashed var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--muted)',
                background: '#1c1917'
              }}
            >
              Original photo reference
            </div>
          )}
        </figure>
        <figure style={{ margin: 0 }}>
          <figcaption className="field-helper" style={{ fontWeight: 600, marginBottom: '6px' }}>
            Renovated Still Concept
          </figcaption>
          <img
            key={afterUrl}
            src={afterUrl}
            alt={`Renovated ${roomName} concept`}
            loading="eager"
            style={{
              width: '100%',
              maxHeight: '480px',
              objectFit: 'contain',
              borderRadius: '8px',
              border: '1px solid var(--border)',
              background: '#1c1917',
              display: 'block'
            }}
            onError={(e) => {
              const target = e.currentTarget;
              if (!target.dataset.proxyTried && afterUrl.startsWith('http')) {
                target.dataset.proxyTried = 'true';
                target.src = `/api/proxy-image?url=${encodeURIComponent(afterUrl)}`;
              }
            }}
          />
        </figure>
      </div>
    </div>
  );
}
