import React from 'react';
import { ExportResponse } from '../../api/types';

interface ExportPanelProps {
  exportData: ExportResponse | null;
  onRefresh?: () => void;
}

export const ExportPanel: React.FC<ExportPanelProps> = ({ exportData, onRefresh }) => {
  if (!exportData) {
    return null;
  }

  return (
    <section
      aria-label="Presentation Export Package"
      data-testid="export-panel"
      style={{
        border: '1px solid #cbd5e1',
        borderRadius: 8,
        padding: 16,
        backgroundColor: '#ffffff',
        marginBottom: 16,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 16, color: '#0f172a' }}>
            Export &amp; Renovator Handoff Package
          </h3>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
            Status:{' '}
            <strong data-testid="export-status-badge" style={{ textTransform: 'uppercase' }}>
              {exportData.status}
            </strong>{' '}
            • Manifest: <code>{exportData.manifest_hash.slice(0, 12)}</code>
          </div>
        </div>
        {onRefresh && exportData.status !== 'ready' && (
          <button
            type="button"
            onClick={onRefresh}
            style={{
              padding: '6px 12px',
              fontSize: 12,
              borderRadius: 4,
              border: '1px solid #cbd5e1',
              backgroundColor: '#f8fafc',
              cursor: 'pointer',
            }}
          >
            Refresh Status
          </button>
        )}
      </div>

      <div
        data-testid="concept-limitation-notice"
        style={{
          padding: '10px 12px',
          backgroundColor: '#fffbeb',
          border: '1px solid #fde68a',
          borderRadius: 6,
          fontSize: 13,
          color: '#92400e',
          marginBottom: 14,
        }}
      >
        <strong>Concept Notice:</strong> {exportData.concept_limitation_notice}
      </div>

      {exportData.status === 'ready' && (
        <div style={{ display: 'grid', gap: 16 }}>
          {exportData.presentation_video_url && (
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                Assembled House Presentation Video (1280×720 MP4)
              </div>
              <video
                data-testid="presentation-video-player"
                src={exportData.presentation_video_url}
                controls
                playsInline
                style={{
                  width: '100%',
                  maxWidth: 640,
                  borderRadius: 6,
                  backgroundColor: '#0f172a',
                  display: 'block',
                  marginBottom: 8,
                }}
              />
              <a
                href={exportData.presentation_video_url}
                download="house_renovation_presentation.mp4"
                data-testid="download-presentation-video"
                style={{
                  display: 'inline-block',
                  padding: '6px 12px',
                  backgroundColor: '#0f766e',
                  color: '#ffffff',
                  borderRadius: 4,
                  fontSize: 13,
                  textDecoration: 'none',
                  fontWeight: 600,
                }}
              >
                Download Presentation MP4
              </a>
            </div>
          )}

          {exportData.room_media.length > 0 && (
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                Accepted Room Media Files
              </div>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, display: 'grid', gap: 4 }}>
                {exportData.room_media.map((item) => (
                  <li key={`${item.kind}-${item.asset_id}`}>
                    <strong>{item.room_name}</strong> ({item.kind}):{' '}
                    <a
                      href={item.download_url}
                      download={item.filename}
                      data-testid={`export-media-${item.kind}-${item.room_id}`}
                    >
                      {item.filename}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {exportData.brief_markdown && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>Renovator Handoff Brief (Markdown)</span>
                {exportData.brief_markdown_url && (
                  <a
                    href={exportData.brief_markdown_url}
                    download="renovation_handoff_brief.md"
                    data-testid="download-brief-markdown"
                    style={{ fontSize: 12, color: '#0f766e', fontWeight: 600 }}
                  >
                    Download Brief (.md)
                  </a>
                )}
              </div>
              <pre
                data-testid="export-brief-markdown"
                style={{
                  margin: 0,
                  padding: 12,
                  backgroundColor: '#f8fafc',
                  border: '1px solid #e2e8f0',
                  borderRadius: 6,
                  fontSize: 12,
                  whiteSpace: 'pre-wrap',
                  maxHeight: 240,
                  overflowY: 'auto',
                }}
              >
                {exportData.brief_markdown}
              </pre>
            </div>
          )}

          <div style={{ fontSize: 12, color: '#64748b' }}>
            Retention expires at: {new Date(exportData.expires_at).toLocaleString()}
          </div>
        </div>
      )}
    </section>
  );
};
