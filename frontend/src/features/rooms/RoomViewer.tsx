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
  return (
    <div className="card" style={{ marginBottom: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <h2 style={{ margin: 0, fontSize: '1.125rem' }}>1. Upload Room Photo ({room.name})</h2>
      </div>
      {room.thumbnail_url ? (
        <div>
          <img
            src={room.thumbnail_url}
            alt={`${room.name} reference`}
            style={{ width: '100%', maxHeight: '420px', objectFit: 'contain', borderRadius: '8px', background: '#1e1c1a' }}
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
