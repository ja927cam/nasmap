import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { api, refreshSession, setAccessToken, setSessionHandler } from './client';
import type { AuthSession, User } from './types';

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setSessionHandler((session: AuthSession | null) => {
      setUser(session?.user ?? null);
    });
    refreshSession()
      .then((session) => setUser(session?.user ?? null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const session = await api<AuthSession>('/auth/login', {
      method: 'POST',
      body: { email, password },
      retry: false,
    });
    setAccessToken(session.access_token);
    setUser(session.user);
  }, []);

  const register = useCallback(async (email: string, password: string, displayName: string) => {
    const session = await api<AuthSession>('/auth/register', {
      method: 'POST',
      body: { email, password, display_name: displayName },
      retry: false,
    });
    setAccessToken(session.access_token);
    setUser(session.user);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api('/auth/logout', { method: 'POST', retry: false });
    } finally {
      setAccessToken(null);
      setUser(null);
    }
  }, []);

  const refreshUser = useCallback(async () => {
    const me = await api<User>('/auth/me');
    setUser(me);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, logout, refreshUser }),
    [user, loading, login, register, logout, refreshUser],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside AuthProvider');
  return context;
}
