import React, { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { apiClient, SafeAppClientError } from '../../api/client';
import { useAppContext } from '../../app/providers';

export function ConnectModal() {
  const { isConnectModalOpen, closeConnectModal, setConnectionState } = useAppContext();
  const navigate = useNavigate();
  const location = useLocation();
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isConnectModalOpen) {
      setErrorMessage(null);
      setTimeout(() => inputRef.current?.focus(), 20);
    } else {
      setApiKey('');
      setShowKey(false);
    }
  }, [isConnectModalOpen]);

  if (!isConnectModalOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim()) return;
    setSubmitting(true);
    setErrorMessage(null);
    try {
      const res = await apiClient.connectMagicHour(apiKey.trim());
      setApiKey('');
      setShowKey(false);
      setConnectionState(res);
      closeConnectModal();
      if (location.pathname !== '/app') {
        navigate('/app');
      }
    } catch (err) {
      if (err instanceof SafeAppClientError) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('Could not connect Magic Hour key. Please check your key and try again.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="connect-modal-title">
      <div className="modal-card">
        <h2 id="connect-modal-title" style={{ marginTop: 0 }}>
          Connect Magic Hour
        </h2>
        <p className="field-helper">
          Open Magic Hour. Create and copy a key. Return here and paste it.
        </p>
        <ol style={{ paddingLeft: '20px', marginBottom: '16px' }}>
          <li>Open Magic Hour Developer Hub in a new tab.</li>
          <li>Create and copy your API key.</li>
          <li>Return here and paste it below.</li>
        </ol>
        <p style={{ marginBottom: '20px' }}>
          <a
            href="https://magichour.ai/developer?tab=api-keys"
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-secondary"
          >
            Create a Magic Hour key ↗
          </a>
        </p>

        {errorMessage && (
          <div className="alert alert-error" role="alert">
            {errorMessage}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <label htmlFor="mh-api-key-input" className="field-label">
            Magic Hour API key.
          </label>
          <p className="field-helper">
            Your key is sent securely to our server to generate media in your account.
          </p>
          <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
            <input
              ref={inputRef}
              id="mh-api-key-input"
              type={showKey ? 'text' : 'password'}
              className="text-input"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Paste Magic Hour API key"
              autoComplete="off"
              disabled={submitting}
              required
            />
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setShowKey((prev) => !prev)}
              aria-label={showKey ? 'Hide API key' : 'Show API key'}
            >
              {showKey ? 'Hide' : 'Show'}
            </button>
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                setApiKey('');
                closeConnectModal();
              }}
              disabled={submitting}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={submitting || !apiKey.trim()}>
              {submitting ? 'Connecting…' : 'Connect'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
