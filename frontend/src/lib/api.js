// Calls to the MCP Bridge API (shared by the Alexa+ app and both portals).
import { API_URL } from './config.js';

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status; // HTTP status, 0 when the API can't be reached
  }
}

export async function request(method, path, { body, token } = {}) {
  const headers = {};
  if (token) headers.Authorization = 'Bearer ' + token;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let resp;
  try {
    resp = await fetch(API_URL + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError("Can't reach MCP Bridge. Is the API running?", 0);
  }
  if (resp.status === 204) return null;
  let data = null;
  try { data = await resp.json(); } catch { /* empty or not JSON */ }
  if (!resp.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : null;
    throw new ApiError(detail || 'MCP Bridge answered ' + resp.status + '.', resp.status);
  }
  return data;
}

// POST /auth/demo-login -> { user_id, user_token, display_name, email, color, role }
export const demoLogin = (username) => request('POST', '/auth/demo-login', { body: { username: String(username || '').trim() } });

// Accounts offered on a sign-in screen: role user | owner | reviewer.
export const demoUsers = (role = 'user') => request('GET', '/auth/demo-users?role=' + encodeURIComponent(role));

// What is not built yet (GET /features), for the "Not built yet" badges.
export const features = () => request('GET', '/features');

// A signed-in session for one account: request() with its token, signing in again on a 401.
export function session(profile) {
  let current = profile;
  async function call(method, path, body) {
    try {
      return await request(method, path, { body, token: current.user_token });
    } catch (e) {
      if (e.status !== 401) throw e;
      current = await demoLogin(current.user_id);
      return request(method, path, { body, token: current.user_token });
    }
  }
  return {
    get profile() { return current; },
    get: (path) => call('GET', path),
    post: (path, body = {}) => call('POST', path, body),
    patch: (path, body) => call('PATCH', path, body),
    del: (path) => call('DELETE', path),
  };
}
