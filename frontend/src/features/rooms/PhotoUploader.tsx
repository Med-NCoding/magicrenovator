import React, { useEffect, useState } from 'react';
import { apiClient, SafeAppClientError } from '../../api/client';
import { AssetMetadataResponse, RoomAnnotation, RoomSummary } from '../../api/types';

interface PhotoUploaderProps {
  room: RoomSummary;
  onUploaded: (asset: AssetMetadataResponse) => void;
}

export function PhotoUploader({ room, onUploaded }: PhotoUploaderProps) {
  const [asset, setAsset] = useState<AssetMetadataResponse | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [annotationLabel, setAnnotationLabel] = useState('');

  useEffect(() => {
    let active = true;
    if (room.primary_asset_id) {
      apiClient
        .getAssetMetadata(room.primary_asset_id)
        .then((meta) => {
          if (active) setAsset(meta);
        })
        .catch(() => {
          // Ignore if asset not yet loaded
        });
    } else {
      setAsset(null);
    }
    return () => {
      active = false;
    };
  }, [room.primary_asset_id]);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const uploaded = await apiClient.uploadRoomPhoto(room.id, file);
      setAsset(uploaded);
      onUploaded(uploaded);
    } catch (err) {
      if (err instanceof SafeAppClientError) {
        setError(err.message);
      } else {
        setError('Could not upload room photo. Please check the file format and try again.');
      }
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  const handleAddAnnotation = async (e: React.MouseEvent<HTMLDivElement>) => {
    if (!asset || !annotationLabel.trim()) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, Number(((e.clientX - rect.left) / rect.width).toFixed(3))));
    const y = Math.min(1, Math.max(0, Number(((e.clientY - rect.top) / rect.height).toFixed(3))));
    const nextAnnotations: RoomAnnotation[] = [
      ...(asset.annotations || []),
      { label: annotationLabel.trim(), x, y, width: 0.12, height: 0.12 },
    ];
    try {
      const updated = await apiClient.updateAssetAnnotations(asset.id, nextAnnotations);
      setAsset(updated);
      setAnnotationLabel('');
      onUploaded(updated);
    } catch (err) {
      if (err instanceof SafeAppClientError) {
        setError(err.message);
      }
    }
  };

  const handleClearAnnotations = async () => {
    if (!asset) return;
    try {
      const updated = await apiClient.updateAssetAnnotations(asset.id, []);
      setAsset(updated);
      onUploaded(updated);
    } catch {
      // Ignore
    }
  };

  return (
    <section className="card" aria-labelledby="photo-section-title" style={{ marginBottom: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h3 id="photo-section-title" style={{ margin: 0 }}>
            1. Room Reference Photo ({room.name})
          </h3>
          <p className="field-helper" style={{ marginBottom: 0 }}>
            Use a wide corner shot in clear daylight with visible fixed features (windows, doors, cabinets, island). Accepted formats: JPEG, PNG, WebP up to 15 MiB.
          </p>
        </div>
        <label className="btn btn-secondary" style={{ cursor: uploading ? 'wait' : 'pointer' }}>
          {uploading ? 'Normalizing Photo…' : asset ? 'Replace Room Photo' : 'Upload Room Photo'}
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp,.heic,.heif"
            onChange={handleFileChange}
            disabled={uploading}
            style={{ display: 'none' }}
            data-testid="room-photo-input"
          />
        </label>
      </div>

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

      {asset && (
        <div style={{ marginTop: '16px' }}>
          {asset.blur_advisory && asset.advisory_message && (
            <div
              role="status"
              style={{
                marginBottom: '12px',
                padding: '10px 12px',
                borderRadius: '8px',
                background: '#FFFBEB',
                border: '1px solid #FCD34D',
                color: '#92400E',
                fontSize: '0.875rem',
              }}
            >
              <strong>Photo Advisory:</strong> {asset.advisory_message}
            </div>
          )}

          <div
            onClick={handleAddAnnotation}
            style={{
              position: 'relative',
              display: 'inline-block',
              maxWidth: '100%',
              borderRadius: '8px',
              overflow: 'hidden',
              border: '1px solid var(--border)',
              cursor: annotationLabel.trim() ? 'crosshair' : 'default',
            }}
          >
            <img
              src={asset.download_url}
              alt={`${room.name} reference`}
              style={{ display: 'block', maxWidth: '100%', maxHeight: '420px', objectFit: 'contain' }}
            />
            {asset.annotations?.map((ann, idx) => (
              <span
                key={`${ann.label}-${idx}`}
                style={{
                  position: 'absolute',
                  left: `${ann.x * 100}%`,
                  top: `${ann.y * 100}%`,
                  transform: 'translate(-50%, -50%)',
                  background: 'rgba(15, 118, 110, 0.92)',
                  color: '#fff',
                  padding: '2px 8px',
                  borderRadius: '999px',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  pointerEvents: 'none',
                }}
              >
                {ann.label}
              </span>
            ))}
          </div>

          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '8px', alignItems: 'center' }}>
            <span className="badge badge-neutral">
              Normalized {asset.width}×{asset.height}px
            </span>
            {asset.orientation_applied && <span className="badge badge-neutral">EXIF Upright Applied</span>}
            {asset.alpha_flattened && <span className="badge badge-neutral">Alpha Flattened</span>}
            <span className="badge badge-neutral">EXIF/GPS Stripped</span>
          </div>

          <div style={{ marginTop: '12px', display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              type="text"
              className="field-input"
              style={{ maxWidth: '280px' }}
              placeholder="Optional pin label (e.g., Island, Backsplash)…"
              value={annotationLabel}
              onChange={(e) => setAnnotationLabel(e.target.value)}
            />
            <span className="field-helper" style={{ margin: 0 }}>
              {annotationLabel.trim() ? 'Click anywhere on the photo above to place pin.' : 'Enter a label, then click the photo to mark a feature.'}
            </span>
            {asset.annotations && asset.annotations.length > 0 && (
              <button type="button" className="btn btn-secondary" onClick={handleClearAnnotations}>
                Clear Pins ({asset.annotations.length})
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
