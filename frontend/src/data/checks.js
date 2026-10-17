// The 8 automated checks and the report builder, from the prototype.
export const CHECKS = [
  { id: 'schema', title: 'Manifest schema is valid', message: 'manifestVersion 1.0 with publisher, accountLinking, private and openapi blocks present.' },
  { id: 'openapi', title: 'OpenAPI spec is valid', message: 'OpenAPI 3.1.0 · Demo Bistro API 1.0.0 · 3 operations, 3 schemas, every $ref resolves.' },
  { id: 'https', title: 'HTTPS everywhere', message: 'API server, authorization, token, revocation, privacy, terms and logo URLs all use https.' },
  { id: 'hosted', title: 'Hosted copy matches the upload', message: 'https://demobistro.test/.well-known/alexa-connector.json matches the upload with the private block excluded. Domain ownership verified.' },
  { id: 'domain', title: "API host is on the owner's domain", message: 'api.demobistro.test belongs to demobistro.test.' },
  { id: 'voice', title: 'Every endpoint is ready for voice', message: '3 of 3 endpoints have a description, at least 2 example phrases, a sideEffect and a speakableResponse.' },
  { id: 'payment', title: 'Payment endpoints require confirmation', message: 'place_order (payment) has requiresConfirmation: true and a confirmationPrompt.' },
  { id: 'limit', title: '20 endpoints or fewer', message: '3 endpoints.' }
];
export function checkReport(overrides) {
  return { passed: !overrides || !Object.values(overrides).some((o) => o.status === 'err'), checks: CHECKS.map((c) => Object.assign({ status: 'ok' }, c, (overrides || {})[c.id] || {})) };
}
