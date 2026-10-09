import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { apiClient } from '../api/client';
import { ConnectionStatusResponse, SessionResponse } from '../api/types';

interface AppContextValue {
  session: SessionResponse | null;
  connection: ConnectionStatusResponse | null;
  isConnectModalOpen: boolean;
  openConnectModal: () => void;
  closeConnectModal: () => void;
  refreshConnection: () => Promise<ConnectionStatusResponse | null>;
  setConnectionState: (c: ConnectionStatusResponse | null) => void;
  loadingSession: boolean;
}

const AppContext = createContext<AppContextValue | undefined>(undefined);

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [connection, setConnection] = useState<ConnectionStatusResponse | null>(null);
  const [isConnectModalOpen, setIsConnectModalOpen] = useState(false);
  const [loadingSession, setLoadingSession] = useState(true);
  const lastFocusRefreshRef = useRef<number>(0);

  const refreshConnection = useCallback(async (): Promise<ConnectionStatusResponse | null> => {
    try {
      const res = await apiClient.refreshConnectionBalance();
      setConnection(res);
      return res;
    } catch {
      try {
        const fallback = await apiClient.getConnectionStatus();
        setConnection(fallback);
        return fallback;
      } catch {
        return null;
      }
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const sess = await apiClient.initSession();
        if (!mounted) return;
        setSession(sess);
        try {
          const conn = await apiClient.getConnectionStatus();
          if (mounted) setConnection(conn);
        } catch {
          // Connection route may not have active key yet
        }
      } catch {
        // Handled by UI
      } finally {
        if (mounted) setLoadingSession(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  // Return refresh debounce on window focus (at most once every 15 seconds)
  useEffect(() => {
    const onFocus = () => {
      const now = Date.now();
      if (connection?.connected && now - lastFocusRefreshRef.current > 15000) {
        lastFocusRefreshRef.current = now;
        void refreshConnection();
      }
    };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [connection?.connected, refreshConnection]);

  return (
    <AppContext.Provider
      value={{
        session,
        connection,
        isConnectModalOpen,
        openConnectModal: () => setIsConnectModalOpen(true),
        closeConnectModal: () => setIsConnectModalOpen(false),
        refreshConnection,
        setConnectionState: setConnection,
        loadingSession,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useAppContext(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) {
    throw new Error('useAppContext must be used inside AppProviders');
  }
  return ctx;
}
