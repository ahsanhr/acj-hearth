const API_BASE = (
  document.querySelector('meta[name="api-base"]')?.content || '/api/v1'
).replace(/\/$/, '');

let accessToken = null;
let refreshPending = null;

export class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

export async function request(
  path,
  { method = 'GET', body, authenticated = false } = {},
) {
  const headers = {};

  if (body !== undefined) headers['Content-Type'] = 'application/json';

  if (authenticated) {
    if (!accessToken) {
      throw new ApiError('Please sign in again.', 401);
    }
    headers.Authorization = `Bearer ${accessToken}`;
  }

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      credentials: 'include',
      ...(body !== undefined && { body: JSON.stringify(body) }),
    });
  } catch {
    throw new ApiError(
      'Unable to reach the server. Check your connection.',
      0,
      'network_error',
    );
  }

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    if (authenticated && response.status === 401) accessToken = null;
    throw new ApiError(
      data?.error?.message ?? 'The request could not be completed.',
      response.status,
      data?.error?.code,
    );
  }

  return data;
}

export async function login(email, password) {
  const result = await request('/auth/login', {
    method: 'POST',
    body: { email, password },
  });
  accessToken = result.access_token;
}

export function restoreSession() {
  if (refreshPending) return refreshPending;

  // Refresh cookies rotate once. Serialize consumption across same-origin tabs.
  // Without Web Locks, require explicit login rather than risk a refresh race.
  if (!navigator.locks) {
    return Promise.reject(new ApiError('Please sign in to continue.', 401));
  }

  refreshPending = navigator.locks.request('hearth-session-refresh', async () => {
    try {
      const result = await request('/auth/refresh', { method: 'POST' });
      accessToken = result.access_token;
    } catch (error) {
      accessToken = null;
      throw error;
    }
  }).finally(() => {
    refreshPending = null;
  });

  return refreshPending;
}

export function getProfile() {
  return request('/users/me', { authenticated: true });
}

export function saveName(name, password) {
  return request('/users/me', {
    method: 'PATCH',
    authenticated: true,
    body: { name, current_password: password },
  });
}
