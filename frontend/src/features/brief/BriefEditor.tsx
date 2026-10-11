import React, { useEffect, useState } from 'react';
import { BriefRevisionResponse } from '../../api/types';
import { PreserveControls } from './PreserveControls';

export function BriefEditor({
  activeBrief,
  onSaveBrief,
  onDraftChange,
  disabled = false,
}: {
  activeBrief: BriefRevisionResponse | null;
  onSaveBrief: (payload: {
    raw_text: string;
    preserve: string[];
    layout_mode: 'preserve' | 'conceptual_change';
    resolve_conflicts?: string[];
  }) => Promise<BriefRevisionResponse | void>;
  onDraftChange?: (draft: {
    raw_text: string;
    preserve: string[];
    layout_mode: 'preserve' | 'conceptual_change';
    isDirty: boolean;
  }) => void;
  disabled?: boolean;
}) {
  const [rawText, setRawText] = useState(
    activeBrief?.brief?.raw_request || (activeBrief as any)?.brief?.raw_text || ''
  );
  const [preserve, setPreserve] = useState<string[]>(
    activeBrief?.brief?.preserve || [
      'Room footprint',
      'Camera viewpoint',
      'Doors',
      'Windows',
      'Ceiling height',
    ]
  );
  const [layoutMode, setLayoutMode] = useState<'preserve' | 'conceptual_change'>(
    activeBrief?.brief?.layout_mode || 'preserve'
  );
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (activeBrief) {
      setRawText(activeBrief.brief?.raw_request || (activeBrief as any)?.brief?.raw_text || '');
      setPreserve(
        activeBrief.brief?.preserve || [
          'Room footprint',
          'Camera viewpoint',
          'Doors',
          'Windows',
          'Ceiling height',
        ]
      );
      setLayoutMode(activeBrief.brief?.layout_mode || 'preserve');
    } else {
      setRawText('');
      setPreserve([
        'Room footprint',
        'Camera viewpoint',
        'Doors',
        'Windows',
        'Ceiling height',
      ]);
      setLayoutMode('preserve');
    }
  }, [activeBrief?.id, activeBrief?.brief?.raw_request, (activeBrief as any)?.brief?.raw_text]);

  useEffect(() => {
    if (!onDraftChange) return;
    const briefRaw = activeBrief?.brief?.raw_request || (activeBrief as any)?.brief?.raw_text || '';
    const briefPreserve = activeBrief?.brief?.preserve || [];
    const briefLayout = activeBrief?.brief?.layout_mode || 'preserve';
    const isDirty = Boolean(
      rawText.trim() &&
        (!activeBrief ||
          rawText.trim() !== briefRaw.trim() ||
          layoutMode !== briefLayout ||
          preserve.join('|') !== briefPreserve.join('|'))
    );
    onDraftChange({
      raw_text: rawText.trim(),
      preserve,
      layout_mode: layoutMode,
      isDirty,
    });
  }, [rawText, preserve, layoutMode, activeBrief, onDraftChange]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!rawText.trim() || saving) return;
    setSaving(true);
    try {
      await onSaveBrief({
        raw_text: rawText.trim(),
        preserve,
        layout_mode: layoutMode,
      });
    } finally {
      setSaving(false);
    }
  };

  const handleResolveConflicts = async () => {
    if (!activeBrief || !rawText.trim() || saving) return;
    setSaving(true);
    try {
      await onSaveBrief({
        raw_text: rawText.trim(),
        preserve,
        layout_mode: layoutMode,
        resolve_conflicts: activeBrief.brief?.unresolved || [],
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="card" style={{ marginBottom: '20px' }} data-testid="brief-editor">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
        <h2 style={{ margin: 0, fontSize: '1.125rem' }}>2. Describe Your Renovation Prompt</h2>
        {activeBrief && (
          <span className="badge badge-neutral" data-testid="brief-revision-badge">
            Revision #{activeBrief.revision_number}
          </span>
        )}
      </div>
      <label htmlFor="brief-raw-text" className="field-label">
        What changes do you want Magic Hour to make?
      </label>
      <textarea
        id="brief-raw-text"
        data-testid="brief-raw-text"
        className="textarea-input"
        rows={3}
        value={rawText}
        onChange={(e) => setRawText(e.target.value)}
        placeholder="e.g., Paint the walls warm white, replace the floor with light oak, and keep the windows and furniture positions."
        disabled={disabled || saving}
        required
      />
      <PreserveControls
        selected={preserve}
        onChange={setPreserve}
        layoutMode={layoutMode}
        onLayoutModeChange={setLayoutMode}
      />
      <div style={{ marginTop: '16px', display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
        <button
          type="submit"
          data-testid="save-brief-btn"
          className="btn btn-primary"
          disabled={disabled || saving || !rawText.trim()}
        >
          {saving ? 'Saving Brief…' : activeBrief ? 'Save Revised Prompt' : 'Save Renovation Brief'}
        </button>
      </div>

      {activeBrief && activeBrief.has_unresolved_conflicts && (
        <div
          role="alert"
          data-testid="brief-conflict-alert"
          style={{
            marginTop: '14px',
            padding: '12px',
            borderRadius: '8px',
            background: '#FFFBEB',
            border: '1px solid #F59E0B',
            color: '#92400E',
          }}
        >
          <strong>Preservation Conflict Detected:</strong>
          <ul style={{ margin: '6px 0', paddingLeft: '18px', fontSize: '0.875rem' }}>
            {(activeBrief.brief?.unresolved || []).map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
          <button
            type="button"
            className="btn btn-secondary"
            data-testid="resolve-brief-conflicts-btn"
            onClick={handleResolveConflicts}
          >
            Acknowledge &amp; Resolve Conflict
          </button>
        </div>
      )}

      {activeBrief && !activeBrief.has_unresolved_conflicts && (
        <div
          data-testid="compiled-prompt-preview"
          style={{
            marginTop: '14px',
            padding: '10px 12px',
            borderRadius: '8px',
            background: 'var(--surface-subtle)',
            border: '1px solid var(--border)',
            fontSize: '0.82rem',
          }}
        >
          <strong>Saved Prompt (Revision #{activeBrief.revision_number}):</strong>
          <div style={{ marginTop: '4px', color: 'var(--text-muted)' }}>
            {activeBrief.brief?.raw_request || (activeBrief as any)?.brief?.raw_text || ''}
          </div>
        </div>
      )}
    </form>
  );
}
