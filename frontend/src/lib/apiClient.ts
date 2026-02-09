const rawBase = (import.meta.env.VITE_API_BASE_URL || '').trim();
if (!rawBase) {
  const message = 'VITE_API_BASE_URL is not set. Configure it in your .env/.env.local before running the frontend.';
  throw new Error(message);
}

const API_BASE_URL = rawBase.replace(/\/+$/, '') || '/';
const CLIENT_ID_KEY = 'tradar_client_id';
let cachedClientId: string | null = null;

function getClientId(): string {
  if (cachedClientId) return cachedClientId;
  try {
    cachedClientId = window.localStorage.getItem(CLIENT_ID_KEY);
  } catch {
    cachedClientId = null;
  }
  if (!cachedClientId) {
    if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
      cachedClientId = crypto.randomUUID();
    } else {
      cachedClientId = `anon-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
    }
    try {
      window.localStorage.setItem(CLIENT_ID_KEY, cachedClientId);
    } catch {
      // ignore storage failures
    }
  }
  return cachedClientId;
}

function buildUrl(path: string): string {
  if (!path || !path.startsWith('/')) {
    throw new Error(`API path must start with '/' - received: ${path}`);
  }
  if (API_BASE_URL === '/') {
    return path;
  }
  return `${API_BASE_URL}${path}`;
}

function previewText(text: string, length = 200): string {
  if (!text) return '';
  return text.length > length ? `${text.slice(0, length)}…` : text;
}

export async function apiFetch(path: string, init?: RequestInit) {
  const url = buildUrl(path);
  const headers = new Headers(init?.headers || {});
  const clientId = getClientId();
  if (clientId) {
    headers.set('X-Client-Id', clientId);
  }
  const response = await fetch(url, { ...init, headers });
  const contentType = response.headers.get('content-type') || '';
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`Request failed (${response.status} ${response.statusText}). Body: ${previewText(text)}`);
  }
  if (!contentType.includes('application/json')) {
    throw new Error(
      `Expected JSON response from ${url} but received content-type '${contentType || 'unknown'}'. Body preview: ${previewText(text)}`,
    );
  }
  try {
    return JSON.parse(text);
  } catch (err) {
    throw new Error(`Failed to parse JSON from ${url}: ${previewText(text)}`);
  }
}

export function buildApiUrl(path: string): string {
  return buildUrl(path);
}

export { API_BASE_URL };
