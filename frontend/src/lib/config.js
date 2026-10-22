// Where the MCP Bridge API + gateway live, and whether to use the in-browser mock instead.
//   VITE_API_URL unset -> http://localhost:8000 (npm run dev against the local stack)
//   VITE_API_URL=""    -> same origin (the EC2 build: Caddy serves the app and the API together)
//   VITE_MOCK=1        -> no backend at all: client/mockBackend.js (offline demo)
const raw = import.meta.env.VITE_API_URL;
export const API_URL = (raw === undefined ? 'http://localhost:8000' : raw).replace(/\/+$/, '');
export const MOCK = import.meta.env.VITE_MOCK === '1';

// The public base of MCP URLs: the API's origin (absolute even when API_URL is same-origin).
export const GATEWAY_URL = API_URL || (typeof window !== 'undefined' ? window.location.origin : '');
