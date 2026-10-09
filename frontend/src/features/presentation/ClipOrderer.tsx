import React, { useState, useEffect } from 'react';
import { PresentationClipItem, RoomSummary } from '../../api/types';

interface ClipOrdererProps {
  rooms: RoomSummary[];
  initialTitle?: string;
  isAssembling: boolean;
  onAssemble: (title: string, orderedClips: PresentationClipItem[], includeConceptLabel: boolean) => void;
}

export const ClipOrderer: React.FC<ClipOrdererProps> = ({
  rooms,
  initialTitle = 'House Renovation Concept Presentation',
  isAssembling,
  onAssemble,
}) => {
  const [title, setTitle] = useState(initialTitle);
  const [includeConceptLabel, setIncludeConceptLabel] = useState(true);
  const [clips, setClips] = useState<PresentationClipItem[]>([]);

  useEffect(() => {
    const acceptedRooms = rooms.filter((r) => Boolean(r.accepted_clip_asset_id));
    setClips((prev) => {
      if (prev.length === acceptedRooms.length && prev.every((p) => acceptedRooms.some((r) => r.accepted_clip_asset_id === p.asset_id))) {
        return prev;
      }
      return acceptedRooms.map((r) => ({
        asset_id: r.accepted_clip_asset_id as string,
        room_label: r.name.slice(0, 60),
      }));
    });
  }, [rooms]);

  const moveClip = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= clips.length) return;
    const next = [...clips];
    const [removed] = next.splice(index, 1);
    next.splice(target, 0, removed);
    setClips(next);
  };

  const updateLabel = (index: number, newLabel: string) => {
    const next = [...clips];
    next[index] = {
      ...next[index],
      room_label: newLabel.slice(0, 60),
    };
    setClips(next);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (clips.length === 0) return;
    onAssemble(title.trim() || 'House Renovation Concept', clips, includeConceptLabel);
  };

  return (
    <section
      aria-label="House Presentation Clip Orderer"
      style={{
        border: '1px solid #d6d3c9',
        borderRadius: 8,
        padding: 16,
        backgroundColor: '#faf9f5',
        marginBottom: 16,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <h3 style={{ margin: 0, fontSize: 16, color: '#1c1b18' }}>
          Assemble Room-by-Room House Presentation
        </h3>
        <span
          style={{
            fontSize: 12,
            backgroundColor: '#e7f5ef',
            color: '#0f5132',
            padding: '2px 8px',
            borderRadius: 999,
            fontWeight: 600,
          }}
        >
          0 Magic Hour Credits (Local FFmpeg)
        </span>
      </div>
      <p style={{ margin: '0 0 12px', fontSize: 13, color: '#57534e' }}>
        Order your accepted room clips into a single downloadable 1280×720 H.264 MP4 presentation with a renovator handoff brief.
      </p>

      {clips.length === 0 ? (
        <div
          data-testid="no-accepted-clips-notice"
          style={{
            padding: 12,
            borderRadius: 6,
            backgroundColor: '#f5f4f0',
            color: '#57534e',
            fontSize: 13,
          }}
        >
          Accept at least one room video clip to unlock house presentation assembly.
        </div>
      ) : (
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 12 }}>
            <label
              htmlFor="presentation-title-input"
              style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 4 }}
            >
              Presentation Title
            </label>
            <input
              id="presentation-title-input"
              data-testid="presentation-title-input"
              type="text"
              value={title}
              maxLength={120}
              onChange={(e) => setTitle(e.target.value)}
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: 6,
                border: '1px solid #cbd5e1',
                fontSize: 14,
              }}
            />
          </div>

          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
              Clip Sequence ({clips.length} {clips.length === 1 ? 'room' : 'rooms'})
            </div>
            <ol style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: 8 }}>
              {clips.map((clip, idx) => (
                <li
                  key={clip.asset_id}
                  data-testid={`clip-order-item-${idx}`}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: 8,
                    backgroundColor: '#ffffff',
                    border: '1px solid #e2e8f0',
                    borderRadius: 6,
                  }}
                >
                  <span
                    style={{
                      fontWeight: 700,
                      fontSize: 13,
                      color: '#475569',
                      minWidth: 24,
                    }}
                  >
                    #{idx + 1}
                  </span>
                  <input
                    type="text"
                    aria-label={`Room label for clip ${idx + 1}`}
                    data-testid={`clip-label-input-${idx}`}
                    value={clip.room_label}
                    maxLength={60}
                    onChange={(e) => updateLabel(idx, e.target.value)}
                    style={{
                      flex: 1,
                      padding: '6px 8px',
                      borderRadius: 4,
                      border: '1px solid #cbd5e1',
                      fontSize: 13,
                    }}
                  />
                  <button
                    type="button"
                    data-testid={`clip-move-up-${idx}`}
                    disabled={idx === 0}
                    onClick={() => moveClip(idx, -1)}
                    aria-label={`Move clip ${idx + 1} up`}
                    style={{
                      padding: '4px 8px',
                      fontSize: 12,
                      borderRadius: 4,
                      border: '1px solid #cbd5e1',
                      backgroundColor: idx === 0 ? '#f1f5f9' : '#ffffff',
                      cursor: idx === 0 ? 'not-allowed' : 'pointer',
                    }}
                  >
                    ↑ Up
                  </button>
                  <button
                    type="button"
                    data-testid={`clip-move-down-${idx}`}
                    disabled={idx === clips.length - 1}
                    onClick={() => moveClip(idx, 1)}
                    aria-label={`Move clip ${idx + 1} down`}
                    style={{
                      padding: '4px 8px',
                      fontSize: 12,
                      borderRadius: 4,
                      border: '1px solid #cbd5e1',
                      backgroundColor: idx === clips.length - 1 ? '#f1f5f9' : '#ffffff',
                      cursor: idx === clips.length - 1 ? 'not-allowed' : 'pointer',
                    }}
                  >
                    ↓ Down
                  </button>
                </li>
              ))}
            </ol>
          </div>

          <div style={{ marginBottom: 12 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={includeConceptLabel}
                onChange={(e) => setIncludeConceptLabel(e.target.checked)}
              />
              Include &ldquo;Visual concept&rdquo; lower-third overlay on room clips
            </label>
          </div>

          <button
            type="submit"
            data-testid="assemble-presentation-btn"
            disabled={isAssembling || clips.length === 0}
            style={{
              padding: '10px 16px',
              backgroundColor: '#1e293b',
              color: '#ffffff',
              border: 'none',
              borderRadius: 6,
              fontWeight: 600,
              fontSize: 14,
              cursor: isAssembling ? 'wait' : 'pointer',
            }}
          >
            {isAssembling ? 'Assembling Presentation...' : 'Assemble House Presentation'}
          </button>
        </form>
      )}
    </section>
  );
};
