import React from 'react';
import { RoomSummary } from '../../api/types';

export function RoomList({
  rooms,
  activeRoomId,
  onSelectRoom,
  onAddRoom,
  canAddRoom,
}: {
  rooms: RoomSummary[];
  activeRoomId?: string;
  onSelectRoom: (roomId: string) => void;
  onAddRoom: (name: string, roomType: string) => Promise<void>;
  canAddRoom: boolean;
}) {
  const [name, setName] = React.useState('');
  const [roomType, setRoomType] = React.useState('kitchen');

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !canAddRoom) return;
    await onAddRoom(name.trim(), 'room');
    setName('');
  };

  return (
    <aside className="card" aria-label="Rooms in project">
      <h2 style={{ marginTop: 0, fontSize: '1.125rem' }}>Rooms ({rooms.length}/5)</h2>
      <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 16px 0', display: 'grid', gap: '8px' }}>
        {rooms.map((rm) => (
          <li key={rm.id}>
            <button
              type="button"
              className={`btn ${rm.id === activeRoomId ? 'btn-primary' : 'btn-secondary'}`}
              style={{ width: '100%', justifyContent: 'space-between' }}
              onClick={() => onSelectRoom(rm.id)}
            >
              <span>{rm.name}</span>
            </button>
          </li>
        ))}
      </ul>

      {canAddRoom ? (
        <form onSubmit={handleCreate} style={{ display: 'grid', gap: '8px' }}>
          <label htmlFor="add-room-name" className="field-label">
            Add room
          </label>
          <input
            id="add-room-name"
            type="text"
            className="text-input"
            placeholder="e.g., Living Room"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <button type="submit" className="btn btn-secondary">
            + Add Room
          </button>
        </form>
      ) : (
        <p className="field-helper">Maximum of 5 rooms reached for this project.</p>
      )}
    </aside>
  );
}
