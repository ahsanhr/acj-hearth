// Access tokens stay in memory. Refresh tokens are HttpOnly cookies.
let accessToken = null;
let refreshPromise = null;
let sessionVersion = 0;

export class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request(path, { method = 'GET', body, token } = {}) {
  const response = await fetch(`/api/v1${path}`, {
    method,
    credentials: 'include',
    headers: {
      ...(body !== undefined && { 'Content-Type': 'application/json' }),
      ...(token && { Authorization: `Bearer ${token}` }),
    },
    ...(body !== undefined && { body: JSON.stringify(body) }),
  });
  const data = response.status === 204
    ? null
    : await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      data?.error?.message || `Request failed (${response.status}).`,
      response.status,
      data?.error?.code,
    );
  }
  return data;
}

async function cookieOperation(work) {
  // Strict refresh rotation requires coordination between tabs, not just requests.
  if (navigator.locks) {
    return navigator.locks.request('hearth-auth-cookie', work);
  }
  return work();
}

export function clearSession() {
  sessionVersion += 1;
  accessToken = null;
}

export async function login(email, password) {
  clearSession();
  const version = sessionVersion;
  const data = await cookieOperation(() => request('/auth/login', {
    method: 'POST', body: { email, password },
  }));
  if (version === sessionVersion) accessToken = data.access_token;
}

export function refreshSession() {
  if (!refreshPromise) {
    const version = sessionVersion;
    refreshPromise = cookieOperation(async () => {
      const data = await request('/auth/refresh', { method: 'POST' });
      if (version === sessionVersion) accessToken = data.access_token;
    }).finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

export async function logout() {
  clearSession();
  await cookieOperation(() => request('/auth/logout', { method: 'POST' }));
}

export function register(email, password) {
  return request('/users', { method: 'POST', body: { email, password } });
}

export async function api(path, options = {}) {
  const token = accessToken;
  const version = sessionVersion;
  try {
    return await request(path, { ...options, token });
  } catch (error) {
    // A request from an old session must not renew or replace a newer session.
    if (error.status !== 401 || version !== sessionVersion) throw error;
    try {
      // Another request may already have renewed this token.
      if (accessToken === token) await refreshSession();
    } catch (renewalError) {
      if (version !== sessionVersion) throw renewalError;
      clearSession();
      window.dispatchEvent(new CustomEvent('sessionexpired', { detail: renewalError }));
      throw renewalError;
    }
    if (version !== sessionVersion) throw error;
    try {
      return await request(path, { ...options, token: accessToken });
    } catch (retryError) {
      if (retryError.status === 401 && version === sessionVersion) {
        clearSession();
        window.dispatchEvent(new CustomEvent('sessionexpired', { detail: retryError }));
      }
      throw retryError;
    }
  }
}
