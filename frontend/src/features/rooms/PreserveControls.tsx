import React, { useState } from 'react';

const DEFAULT_PRESERVE_OPTIONS = [
  'Room footprint',
  'Windows',
  'Doors',
  'Island position',
  'Appliance positions',
  'Ceiling height',
];

interface PreserveControlsProps {
  preserve: string[];
  layoutMode: 'preserve' | 'conceptual_change';
  onChangePreserve: (next: string[]) => void;
  onChangeLayoutMode: (next: 'preserve' | 'conceptual_change') => void;
}

export function PreserveControls({
  preserve,
  layoutMode,
  onChangePreserve,
  onChangeLayoutMode,
}: PreserveControlsProps) {
  const [customItem, setCustomItem] = useState('');

  const toggleItem = (item: string) => {
    if (preserve.includes(item)) {
      onChangePreserve(preserve.filter((p) => p !== item));
    } else {
      onChangePreserve([...preserve, item]);
    }
  };

  const handleAddCustom = () => {
    const trimmed = customItem.trim();
    if (!trimmed) return;
    if (!preserve.includes(trimmed)) {
      onChangePreserve([...preserve, trimmed]);
    }
    setCustomItem('');
  };

  const allItems = Array.from(new Set([...DEFAULT_PRESERVE_OPTIONS, ...preserve]));

  return (
    <div
      style={{
        padding: '16px',
        background: 'var(--surface-subtle)',
        borderRadius: '8px',
        border: '1px solid var(--border)',
        marginTop: '12px',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
        <strong>What Must Stay Fixed (Preservation Controls)</strong>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <label style={{ fontSize: '0.875rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <input
              type="radio"
              name="layout-mode"
              checked={layoutMode === 'preserve'}
              onChange={() => onChangeLayoutMode('preserve')}
            />
            Lock room layout
          </label>
          <label style={{ fontSize: '0.875rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <input
              type="radio"
              name="layout-mode"
              checked={layoutMode === 'conceptual_change'}
              onChange={() => onChangeLayoutMode('conceptual_change')}
            />
            Allow conceptual layout change
          </label>
        </div>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '12px' }}>
        {allItems.map((item) => {
          const checked = preserve.includes(item);
          return (
            <label
              key={item}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 10px',
                borderRadius: '6px',
                border: checked ? '1px solid var(--accent)' : '1px solid var(--border)',
                background: checked ? '#F0FDFA' : '#FFFFFF',
                fontSize: '0.875rem',
                cursor: 'pointer',
              }}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggleItem(item)}
              />
              {item}
            </label>
          );
        })}
      </div>

      <div style={{ display: 'flex', gap: '8px', marginTop: '12px', flexWrap: 'wrap' }}>
        <input
          type="text"
          className="field-input"
          style={{ maxWidth: '260px' }}
          placeholder="Add custom feature to preserve…"
          value={customItem}
          onChange={(e) => setCustomItem(e.target.value)}
        />
        <button type="button" className="btn btn-secondary" onClick={handleAddCustom}>
          Add Lock
        </button>
      </div>
    </div>
  );
}
