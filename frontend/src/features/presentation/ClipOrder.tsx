import React, { useState } from 'react';
import { PresentationClipItem, RoomSummary } from '../../api/types';

export function ClipOrder({
  rooms,
  onAssemble,
  assembling = false,
}: {
  rooms: RoomSummary[];
  onAssemble: (title: string, orderedClips: PresentationClipItem[], includeConceptLabel: boolean) => Promise<void>;
  assembling?: boolean;
}) {
  const eligibleRooms = rooms.filter((r) => r.accepted_clip_asset_id);
  const [title, setTitle] = useState('Room by room renovation concept');
  const [includeConceptLabel, setIncludeConceptLabel] = useState(true);

  if (eligibleRooms.length === 0) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const clips: PresentationClipItem[] = eligibleRooms.map((r) => ({
      asset_id: r.accepted_clip_asset_id!,
      room_label: r.name,
    }));
    await onAssemble(title, clips, includeConceptLabel);
  };

  return (
    <form onSubmit={handleSubmit} className="card" style={{ marginTop: '16px' }}>
      <h3 style={{ marginTop: 0 }}>Assemble Room-by-Room House Presentation</h3>
      <p className="field-helper">
        Room-by-room renovation concept presentation using cuts (not an inferred continuous floor-plan walkthrough). Local FFmpeg assembly incurs no Magic Hour generation charge.
      </p>
      <label htmlFor="presentation-title" className="field-label">
        Presentation title
      </label>
      <input
        id="presentation-title"
        type="text"
        className="text-input"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <div style={{ marginTop: '12px', marginBottom: '12px' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <input
            type="checkbox"
            checked={includeConceptLabel}
            onChange={(e) => setIncludeConceptLabel(e.target.checked)}
          />
          Include &ldquo;Room by room renovation concept&rdquo; overlay label
        </label>
      </div>
      <button type="submit" className="btn btn-primary" disabled={assembling}>
        {assembling ? 'Assembling Presentation…' : 'Assemble Presentation & Export Brief'}
      </button>
    </form>
  );
}
