import React from 'react';
import { RoomSummary } from '../../api/types';
import { PhotoInput } from './PhotoInput';

export function RoomViewer({
  room,
  onUploadPhoto,
}: {
  room: RoomSummary;
  onUploadPhoto: (file: File) => Promise<void>;
}) {
  const photoUrl =
    (typeof window !== 'undefined' ? localStorage.getItem(`mr_photo_preview_${room.id}`) : null) ||
    (typeof window !== 'undefined' ? localStorage.getItem('mr_photo_preview_latest') : null) ||
    room.thumbnail_url ||
    null;

  return (
    <div className="card" style={{ marginBottom: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <h2 style={{ margin: 0, fontSize: '1.125rem' }}>1. Upload Room Photo ({room.name})</h2>
      </div>
      {photoUrl ? (
        <div>
          <img
            src={photoUrl}
            alt={`${room.name} reference`}
            style={{ width: '100%', maxHeight: '420px', objectFit: 'contain', borderRadius: '8px', background: '#1e1c1a' }}
            onError={(e) => {
              const target = e.currentTarget;
              if (!target.dataset.triedFallback && typeof window !== 'undefined') {
                target.dataset.triedFallback = 'true';
                const stored = localStorage.getItem('mr_photo_preview_latest');
                if (stored && stored !== target.src) target.src = stored;
              }
            }}
          />
          <div style={{ marginTop: '12px' }}>
            <PhotoInput onUpload={onUploadPhoto} />
          </div>
        </div>
      ) : (
        <PhotoInput onUpload={onUploadPhoto} />
      )}
    </div>
  );
}
