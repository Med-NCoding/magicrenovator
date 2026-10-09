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
          <img
            src={beforeUrl}
            alt={`Original ${roomName}`}
            style={{ width: '100%', borderRadius: '8px', border: '1px solid var(--border)' }}
          />
        </figure>
        <figure style={{ margin: 0 }}>
          <figcaption className="field-helper" style={{ fontWeight: 600, marginBottom: '6px' }}>
            Renovated Still Concept
          </figcaption>
          <img
            key={afterUrl}
            src={afterUrl}
            alt={`Renovated ${roomName} concept`}
            style={{ width: '100%', borderRadius: '8px', border: '1px solid var(--border)' }}
          />
        </figure>
      </div>
    </div>
  );
}
