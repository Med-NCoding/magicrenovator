import React from 'react';
import { Link, Route, Routes, useNavigate } from 'react-router-dom';
import { ConnectModal } from '../features/connection/ConnectModal';
import { CreditStatus } from '../features/connection/CreditStatus';
import { ProjectList } from '../features/projects/ProjectList';
import { ProjectWorkspace } from '../features/projects/ProjectWorkspace';
import { useAppContext } from './providers';

function LandingPage() {
  const { connection, openConnectModal } = useAppContext();
  const navigate = useNavigate();

  const handlePrimaryAction = () => {
    if (!connection?.connected) {
      openConnectModal();
    } else {
      navigate('/app');
    }
  };

  return (
    <main style={{ maxWidth: '920px', margin: '0 auto', padding: '32px 24px' }}>
      <div className="card" style={{ marginBottom: '24px' }}>
        <span className="badge badge-connected" style={{ marginBottom: '12px' }}>
          magicrenovator · Powered by Magic Hour
        </span>
        <h1 style={{ marginTop: '8px', fontSize: '2.1rem' }}>
          magicrenovator
        </h1>
        <p style={{ fontSize: '1.1rem', color: 'var(--text-muted)', maxWidth: '720px' }}>
          Visualize room renovations in minutes. Connect your Magic Hour API key, upload a room photo, describe your renovation prompt, choose photo or video output, and download your approved result.
        </p>
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginTop: '20px' }}>
          <button type="button" className="btn btn-primary" onClick={handlePrimaryAction}>
            Connect Magic Hour
          </button>
          <Link to="/app" className="btn btn-secondary">
            Open Projects
          </Link>
        </div>
      </div>

      <section className="card" aria-labelledby="example-heading">
        <h2 id="example-heading" style={{ margin: '0 0 12px 0', fontSize: '1.25rem' }}>
          How It Works
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
          <div style={{ padding: '14px', background: 'var(--surface-subtle)', borderRadius: '8px' }}>
            <strong>1. Upload Photo</strong>
            <p className="field-helper" style={{ marginBottom: 0 }}>
              Upload a wide photo of your room showing the layout and features to keep.
            </p>
          </div>
          <div style={{ padding: '14px', background: 'var(--surface-subtle)', borderRadius: '8px' }}>
            <strong>2. Describe &amp; Choose Format</strong>
            <p className="field-helper" style={{ marginBottom: 0 }}>
              Write your renovation prompt and pick whether you want a Photo or a Video Clip.
            </p>
          </div>
          <div style={{ padding: '14px', background: 'var(--surface-subtle)', borderRadius: '8px' }}>
            <strong>3. Quote, Revise &amp; Approve</strong>
            <p className="field-helper" style={{ marginBottom: 0 }}>
              Check your credit quote, generate on Magic Hour, revise if needed, and approve.
            </p>
          </div>
          <div style={{ padding: '14px', background: 'var(--surface-subtle)', borderRadius: '8px' }}>
            <strong>4. Download Result</strong>
            <p className="field-helper" style={{ marginBottom: 0 }}>
              Once approved, download your renovated room photo or video clip at the bottom of the page.
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}

function HelpPage() {
  return (
    <main style={{ maxWidth: '840px', margin: '0 auto', padding: '32px 24px' }}>
      <div className="card">
        <h1 style={{ marginTop: 0 }}>Magic Hour Key & Credit Instructions</h1>
        <ol style={{ display: 'grid', gap: '12px' }}>
          <li>
            Open{' '}
            <a href="https://magichour.ai/developer?tab=api-keys" target="_blank" rel="noopener noreferrer">
              Magic Hour Developer Hub
            </a>{' '}
            in a new tab to create and copy your API key.
          </li>
          <li>
            Paste the key in magicrenovator&rsquo;s Connect dialog. We validate your key with <code>GET /v1/account</code> and encrypt it in short-lived Redis storage.
          </li>
          <li>
            Every image and video clip shows an explicit credit estimate and requires your confirmation before submission. Top up credits anytime on{' '}
            <a href="https://magichour.ai/pricing" target="_blank" rel="noopener noreferrer">
              Magic Hour Pricing
            </a>
            .
          </li>
        </ol>
      </div>
    </main>
  );
}

function PrivacyPage() {
  return (
    <main style={{ maxWidth: '840px', margin: '0 auto', padding: '32px 24px' }}>
      <div className="card">
        <h1 style={{ marginTop: 0 }}>Privacy, Provider Transfer & Retention Policy</h1>
        <p>
          <strong>Private Photo Normalization:</strong> Uploaded room photos are stripped of EXIF GPS coordinates, camera serial metadata, and embedded thumbnails before private storage.
        </p>
        <p>
          <strong>Provider Transfer:</strong> When you confirm a paid quote, normalized room photos and compiled prompts are sent to Magic Hour using your connected API key. Generated outputs may appear in your Magic Hour library.
        </p>
        <p>
          <strong>Retention & Deletion:</strong> Anonymous session projects and private assets expire after 7 days of inactivity. Deleting a project immediately tombstones app access and schedules local private objects for deletion. Manage copies stored in your Magic Hour account directly at magichour.ai.
        </p>
      </div>
    </main>
  );
}

export function AppRoutes() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <Link to="/" style={{ fontWeight: 700, fontSize: '1.25rem', color: 'var(--text)', textDecoration: 'none' }}>
            magicrenovator
          </Link>
          <nav aria-label="Primary" style={{ display: 'flex', gap: '12px' }}>
            <Link to="/app" style={{ color: 'var(--text-muted)', textDecoration: 'none', fontWeight: 500 }}>
              Projects
            </Link>
            <Link to="/help" style={{ color: 'var(--text-muted)', textDecoration: 'none', fontWeight: 500 }}>
              Help
            </Link>
            <Link to="/privacy" style={{ color: 'var(--text-muted)', textDecoration: 'none', fontWeight: 500 }}>
              Privacy
            </Link>
          </nav>
        </div>
        <CreditStatus />
      </header>

      <ConnectModal />

      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/app" element={<ProjectList />} />
        <Route path="/app/projects/:projectId" element={<ProjectWorkspace />} />
        <Route path="/app/projects/:projectId/rooms/:roomId" element={<ProjectWorkspace />} />
        <Route path="/help" element={<HelpPage />} />
        <Route path="/privacy" element={<PrivacyPage />} />
      </Routes>
    </div>
  );
}
