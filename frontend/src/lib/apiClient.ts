const rawBase = (import.meta.env.VITE_API_BASE_URL || '').trim();
if (!rawBase) {
  const message = 'VITE_API_BASE_URL is not set. Configure it in your .env/.env.local before running the frontend.';
  throw new Error(message);
}

const API_BASE_URL = rawBase.replace(/\/+$/, '') || '/';

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
  const response = await fetch(url, init);
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
