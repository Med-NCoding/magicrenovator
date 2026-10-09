import React from 'react';

export const DEFAULT_PRESERVE_OPTIONS = [
  'Room footprint',
  'Camera viewpoint',
  'Doors',
  'Windows',
  'Ceiling height',
  'Island position',
  'Appliance positions',
  'Furniture positions',
];

export function PreserveControls({
  selected,
  onChange,
  layoutMode,
  onLayoutModeChange,
}: {
  selected: string[];
  onChange: (next: string[]) => void;
  layoutMode: 'preserve' | 'conceptual_change';
  onLayoutModeChange: (mode: 'preserve' | 'conceptual_change') => void;
}) {
  const toggleItem = (item: string) => {
    if (selected.includes(item)) {
      onChange(selected.filter((x) => x !== item));
    } else {
      onChange([...selected, item]);
    }
  };

  return (
    <div style={{ marginTop: '16px' }}>
      <h3 style={{ fontSize: '1rem', marginBottom: '8px' }}>What should stay the same?</h3>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '12px' }}>
        {DEFAULT_PRESERVE_OPTIONS.map((opt) => (
          <label key={opt} style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={selected.includes(opt)}
              onChange={() => toggleItem(opt)}
            />
            <span>{opt}</span>
          </label>
        ))}
      </div>
      <label htmlFor="layout-mode-select" className="field-label">
        Structural layout mode
      </label>
      <select
        id="layout-mode-select"
        className="select-input"
        value={layoutMode}
        onChange={(e) => onLayoutModeChange(e.target.value as 'preserve' | 'conceptual_change')}
      >
        <option value="preserve">Preserve existing structural layout</option>
        <option value="conceptual_change">Allow explicitly requested layout changes</option>
      </select>
    </div>
  );
}
