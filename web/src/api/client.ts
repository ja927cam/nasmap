import type { AuthSession } from './types';

export const API_BASE = import.meta.env.VITE_API_BASE ?? '/api/v1';

let accessToken: string | null = null;
let sessionHandler: ((session: AuthSession | null) => void) | null = null;
let refreshInFlight: Promise<AuthSession | null> | null = null;

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;

  constructor(status: number, message: string, code = 'http_error', details: unknown = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getAccessToken() {
  return accessToken;
}

export function setSessionHandler(handler: (session: AuthSession | null) => void) {
  sessionHandler = handler;
}

async function parseError(response: Response): Promise<ApiError> {
  let code = 'http_error';
  let message = `Request failed with HTTP ${response.status}`;
  let details: unknown = null;
  try {
    const body = await response.json();
    if (body?.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details ?? null;
    } else if (body?.detail) {
      message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      details = body.detail;
    }
  } catch {
    // Non-JSON error; keep the status text.
  }
  return new ApiError(response.status, message, code, details);
}

export async function refreshSession(): Promise<AuthSession | null> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        setAccessToken(null);
        sessionHandler?.(null);
        return null;
      }
      const session = (await response.json()) as AuthSession;
      setAccessToken(session.access_token);
      sessionHandler?.(session);
      return session;
    } catch {
      setAccessToken(null);
      sessionHandler?.(null);
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  retry?: boolean;
  rawBody?: BodyInit;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { retry = true, rawBody, body, headers, ...rest } = options;
  const requestHeaders = new Headers(headers);
  requestHeaders.set('Accept', 'application/json');
  if (accessToken) requestHeaders.set('Authorization', `Bearer ${accessToken}`);
  let payload: BodyInit | undefined = rawBody;
  if (body !== undefined && !(body instanceof FormData)) {
    requestHeaders.set('Content-Type', 'application/json');
    payload = JSON.stringify(body);
  } else if (body instanceof FormData) {
    payload = body;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...rest,
      headers: requestHeaders,
      body: payload,
      credentials: 'include',
    });
  } catch (err) {
    throw new ApiError(0, err instanceof Error ? err.message : 'Network error', 'network_error');
  }

  if (response.status === 401 && retry && !path.startsWith('/auth/')) {
    const session = await refreshSession();
    if (session) {
      return api<T>(path, { ...options, retry: false });
    }
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.includes('application/json')) return (await response.json()) as T;
  return (await response.text()) as T;
}

export async function download(path: string, filename: string) {
  const headers = new Headers();
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
  const response = await fetch(`${API_BASE}${path}`, { headers, credentials: 'include' });
  if (!response.ok) throw await parseError(response);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export async function authedBlob(path: string): Promise<Blob> {
  const headers = new Headers();
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
  const response = await fetch(`${API_BASE}${path.replace(/^\/api\/v1/, '')}`, {
    headers,
    credentials: 'include',
  });
  if (response.status === 401) {
    const session = await refreshSession();
    if (session) return authedBlob(path);
  }
  if (!response.ok) throw await parseError(response);
  return response.blob();
}

export function tileUrl(layerId: string) {
  return `${API_BASE}/layers/${layerId}/tiles/{z}/{x}/{y}.png`;
}

export function vectorTileUrl(layerId: string) {
  return `${API_BASE}/layers/${layerId}/vector-tiles/{z}/{x}/{y}.pbf`;
}

export function wmsTileUrl(layerId: string) {
  return `${API_BASE}/layers/${layerId}/wms?bbox={bbox-epsg-3857}&width=256&height=256&transparent=true`;
}
