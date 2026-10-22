// Minimal MCP client for the gateway: POST /mcp/{service_uuid}, JSON-RPC 2.0, stateless
// Streamable HTTP (plain JSON answers, no session, no SSE). The user token picks the user.
import { API_URL } from '../lib/config.js';

const PROTOCOL_VERSION = '2025-06-18';
let nextId = 1;

export class McpError extends Error {
  constructor(message, { status = null, code = null } = {}) {
    super(message);
    this.status = status; // HTTP status (401 = the user token is missing, expired or unknown)
    this.code = code; // JSON-RPC error code
  }
}

export function mcpClient(serviceUuid, getToken) {
  const url = `${API_URL}/mcp/${serviceUuid}`;
  let initialized = null;

  async function rpc(method, params) {
    let resp;
    try {
      resp = await fetch(url, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${getToken()}`,
          'Content-Type': 'application/json',
          Accept: 'application/json, text/event-stream',
          'MCP-Protocol-Version': PROTOCOL_VERSION,
        },
        body: JSON.stringify({ jsonrpc: '2.0', id: nextId++, method, params }),
      });
    } catch {
      throw new McpError("Can't reach MCP Bridge. Is the API running?");
    }
    if (resp.status === 401) throw new McpError('Your session expired. Sign in again.', { status: 401 });
    if (resp.status === 404) throw new McpError("This service isn't published yet.", { status: 404 });
    let body;
    try { body = await resp.json(); } catch { throw new McpError('The gateway sent an unreadable answer.', { status: resp.status }); }
    if (body.error) throw new McpError(body.error.message || 'MCP error', { status: resp.status, code: body.error.code });
    return body.result;
  }

  function init() {
    initialized = initialized || rpc('initialize', {
      protocolVersion: PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: { name: 'mcp-bridge-simulator', version: '1.0' },
    }).catch((e) => { initialized = null; throw e; });
    return initialized;
  }

  return {
    url,
    init,
    async listTools() {
      await init();
      return (await rpc('tools/list', {})).tools || [];
    },
    // -> { text, data, isError } where data is the parsed JSON the tool returned (if any)
    async callTool(name, args) {
      await init();
      const result = await rpc('tools/call', { name, arguments: args || {} });
      const text = (result.content || []).filter((c) => c.type === 'text').map((c) => c.text).join('\n');
      let data = result.structuredContent ?? null;
      if (data == null) { try { data = JSON.parse(text); } catch { data = null; } }
      return { text, data, isError: !!result.isError };
    },
  };
}
