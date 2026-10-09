import React, { useState } from 'react';
import { apiClient } from '../../api/client';
import { useAppContext } from '../../app/providers';

export function CreditStatus() {
  const { connection, openConnectModal, refreshConnection, setConnectionState } = useAppContext();
  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshConnection();
    } finally {
      setRefreshing(false);
    }
  };

  const handleDisconnect = async () => {
    const res = await apiClient.disconnectMagicHour();
    setConnectionState(res);
  };

  if (!connection?.connected) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <button type="button" className="btn btn-primary" onClick={openConnectModal}>
          Connect Magic Hour
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
      <span className="badge badge-connected" data-testid="connection-pill">
        Magic Hour connected ({connection.masked_key}) · {connection.credits ?? 0} credits
      </span>
      <button
        type="button"
        className="btn btn-secondary"
        onClick={handleRefresh}
        disabled={refreshing}
      >
        {refreshing ? 'Refreshing…' : 'Refresh balance'}
      </button>
      <a
        href="https://magichour.ai/pricing"
        target="_blank"
        rel="noopener noreferrer"
        className="btn btn-secondary"
      >
        Add credits ↗
      </a>
      <button type="button" className="btn btn-secondary" onClick={handleDisconnect}>
        Disconnect
      </button>
    </div>
  );
}
