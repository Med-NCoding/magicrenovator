import React, { useEffect, useState } from 'react';
import { apiClient, SafeAppClientError } from '../../api/client';
import { BriefRevisionResponse, Change, RoomAnnotation, RoomSummary } from '../../api/types';
import { PreserveControls } from './PreserveControls';

const INITIAL_PRESERVE = [
  'Room footprint',
  'Windows',
  'Doors',
  'Island position',
  'Appliance positions',
  'Ceiling height',
];

interface BriefEditorProps {
  room: RoomSummary;
  annotations?: RoomAnnotation[];
  onBriefSaved: (revision: BriefRevisionResponse) => void;
}

export function BriefEditor({ room, annotations = [], onBriefSaved }: BriefEditorProps) {
  const [rawText, setRawText] = useState(
    'Change the cabinet fronts to matte white, change the floor appearance to light oak, and change the handles to brass.'
  );
  const [style, setStyle] = useState('Warm modern residential');
  const [preserve, setPreserve] = useState<string[]>(INITIAL_PRESERVE);
  const [layoutMode, setLayoutMode] = useState<'preserve' | 'conceptual_change'>('preserve');
  const [changes, setChanges] = useState<Change[]>([]);
  const [useCustomChanges, setUseCustomChanges] = useState(false);
  const [revision, setRevision] = useState<BriefRevisionResponse | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    apiClient
      .getLatestRoomBrief(room.id)
      .then((res) => {
        if (!active || !res) return;
        setRevision(res);
        setRawText(res.brief.raw_request);
        setStyle(res.brief.style || '');
        setPreserve(res.brief.preserve);
        setLayoutMode(res.brief.layout_mode);
        setChanges(res.brief.changes);
        onBriefSaved(res);
      })
      .catch(() => {
        // No brief saved yet
      });
    return () => {
      active = false;
    };
  }, [room.id]);

  const handleSaveBrief = async (resolveConflicts: string[] = []) => {
    setSaving(true);
    setError(null);
    try {
      const saved = await apiClient.saveRoomBrief(room.id, {
        raw_text: rawText,
        changes: useCustomChanges ? changes : undefined,
        preserve,
        layout_mode: layoutMode,
        style: style.trim() || null,
        resolve_conflicts: resolveConflicts,
        parent_revision_id: revision?.id || null,
        accepted_reference_asset_id: room.accepted_image_asset_id || null,
        annotations,
      });
      setRevision(saved);
      setPreserve(saved.brief.preserve);
      setChanges(saved.brief.changes);
      onBriefSaved(saved);
    } catch (err) {
      if (err instanceof SafeAppClientError) {
        setError(err.message);
      } else {
        setError('Could not save renovation brief. Please check your inputs.');
      }
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateChange = (idx: number, field: 'target' | 'description', value: string) => {
    setUseCustomChanges(true);
    setChanges((prev) =>
      prev.map((c, i) => (i === idx ? { ...c, [field]: value, source: 'user_control' } : c))
    );
  };

  const handleRemoveChange = (idx: number) => {
    setUseCustomChanges(true);
    setChanges((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleAddChange = () => {
    setUseCustomChanges(true);
    setChanges((prev) => [
      ...prev,
      { target: 'Cabinets', description: 'Matte white fronts', source: 'user_control' },
    ]);
  };

  return (
    <section className="card" aria-labelledby="brief-section-title" style={{ marginBottom: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
        <div>
          <h3 id="brief-section-title" style={{ margin: 0 }}>
            2. Renovation Brief & Preservation Controls
          </h3>
          <p className="field-helper" style={{ marginBottom: 0 }}>
            Describe requested surface, material, and fixture updates. Review the parsed change list and resolve any conflicts before requesting a quote.
          </p>
        </div>
        {revision && (
          <span className="badge badge-neutral">
            Revision #{revision.revision_number} · {revision.compiler_version}
          </span>
        )}
      </div>

      <div style={{ marginTop: '14px' }}>
        <label className="field-label" htmlFor="brief-raw-input">
          Plain-Language Renovation Request
        </label>
        <textarea
          id="brief-raw-input"
          className="field-input"
          rows={3}
          value={rawText}
          onChange={(e) => {
            setRawText(e.target.value);
            setUseCustomChanges(false);
          }}
          placeholder="Example: Change the cabinet fronts to matte white, change the floor appearance to light oak, and change the handles to brass."
        />
      </div>

      <div style={{ marginTop: '12px' }}>
        <label className="field-label" htmlFor="brief-style-input">
          Optional Style Direction
        </label>
        <input
          id="brief-style-input"
          type="text"
          className="field-input"
          value={style}
          onChange={(e) => setStyle(e.target.value)}
          placeholder="e.g., Warm Scandinavian, Modern Coastal, Classic Shaker"
        />
      </div>

      <PreserveControls
        preserve={preserve}
        layoutMode={layoutMode}
        onChangePreserve={setPreserve}
        onChangeLayoutMode={setLayoutMode}
      />

      {changes.length > 0 && (
        <div style={{ marginTop: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <strong>Structured Change List (Editable)</strong>
            <button type="button" className="btn btn-secondary" onClick={handleAddChange}>
              + Add Change Item
            </button>
          </div>
          <div style={{ display: 'grid', gap: '8px', marginTop: '8px' }}>
            {changes.map((c, idx) => (
              <div
                key={idx}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '160px 1fr auto',
                  gap: '8px',
                  alignItems: 'center',
                }}
              >
                <input
                  type="text"
                  className="field-input"
                  aria-label={`Change target ${idx + 1}`}
                  value={c.target}
                  onChange={(e) => handleUpdateChange(idx, 'target', e.target.value)}
                />
                <input
                  type="text"
                  className="field-input"
                  aria-label={`Change description ${idx + 1}`}
                  value={c.description}
                  onChange={(e) => handleUpdateChange(idx, 'description', e.target.value)}
                />
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => handleRemoveChange(idx)}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

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

      {revision && revision.brief.unresolved.length > 0 && (
        <div
          role="alert"
          data-testid="brief-conflict-alert"
          style={{
            marginTop: '14px',
            padding: '14px',
            borderRadius: '8px',
            background: '#FFFBEB',
            border: '1px solid #F59E0B',
            color: '#92400E',
          }}
        >
          <strong>Unresolved Brief Conflicts (Quote Blocked Until Resolved):</strong>
          <ul style={{ margin: '8px 0', paddingLeft: '20px' }}>
            {revision.brief.unresolved.map((conflict, idx) => (
              <li key={idx}>{conflict}</li>
            ))}
          </ul>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => handleSaveBrief(revision.brief.unresolved)}
          >
            Override & Unlock Conflicting Preservation Locks
          </button>
        </div>
      )}

      <div style={{ marginTop: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
        <button
          type="button"
          className="btn btn-primary"
          disabled={saving}
          onClick={() => handleSaveBrief([])}
          data-testid="compile-brief-button"
        >
          {saving ? 'Compiling Brief…' : 'Compile & Save Renovation Brief'}
        </button>

        {revision && !revision.has_unresolved_conflicts && (
          <span className="badge badge-ok" data-testid="brief-compiled-badge">
            Brief Ready for Quote
          </span>
        )}
      </div>

      {revision && revision.compiled_prompt && (
        <div
          style={{
            marginTop: '14px',
            padding: '12px',
            borderRadius: '8px',
            background: 'var(--surface-subtle)',
            fontSize: '0.85rem',
          }}
        >
          <strong>Compiled Provider Image Prompt:</strong>
          <p style={{ margin: '4px 0 0', fontFamily: 'var(--font-mono)' }}>{revision.compiled_prompt}</p>
        </div>
      )}
    </section>
  );
}
