// OpenAPI -> MCP tool conversion (C2 MappedEndpoint view), from the prototype.
import { MANIFEST } from './manifest.js';
import { humanize } from '../lib/utils.js';

function schemaType(s) {
  if (!s) return 'any';
  if (s.$ref) return s.$ref.split('/').pop();
  if (s.enum) return s.enum.join(' | ');
  if (s.type === 'array') return 'array of ' + schemaType(s.items);
  return s.type || 'object';
}
export function deriveTools(manifest) {
  const api = manifest.openapi, base = api.servers[0].url, out = [];
  Object.keys(api.paths).forEach((path) => {
    Object.keys(api.paths[path]).forEach((method) => {
      const op = api.paths[path][method], ax = op['x-alexa'] || {};
      const params = (op.parameters || []).map((p) => ({ name: p.name, in: p.in, required: !!p.required, type: schemaType(p.schema), description: p.description, default: p.schema && p.schema.default }));
      if (op.requestBody) {
        const ref = op.requestBody.content['application/json'].schema.$ref.split('/').pop();
        const body = api.components.schemas[ref];
        Object.keys(body.properties).forEach((k) => {
          const pr = body.properties[k];
          params.push({ name: k, in: 'body', required: (body.required || []).includes(k), type: schemaType(pr), description: pr.description, default: pr.default });
        });
      }
      params.sort((a, b) => (b.required ? 1 : 0) - (a.required ? 1 : 0)); // required before optional (C2)
      const se = ax.sideEffect || 'none';
      out.push({
        name: op.operationId, title: op.summary || humanize(op.operationId), description: op.description,
        http: { method: method.toUpperCase(), path, baseUrl: base },
        read_only: method.toUpperCase() === 'GET',
        params,
        annotations: { readOnlyHint: se === 'none', destructiveHint: se !== 'none', idempotentHint: se === 'none', openWorldHint: true },
        sideEffect: se, requiresConfirmation: !!ax.requiresConfirmation,
        confirmationPrompt: ax.confirmationPrompt, speakableResponse: ax.speakableResponse,
        emptyResponse: ax.emptyResponse, errorResponses: ax.errorResponses || {}, examplePhrases: ax.examplePhrases || []
      });
    });
  });
  return out;
}
export const TOOLS = deriveTools(MANIFEST);
