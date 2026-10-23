// Demo Bistro connector manifest and gateway constants (from the prototype).
// One MCP URL per service, the same for every user: {GATEWAY_URL}/mcp/{service_uuid}
// The real gateway's address unless the app runs on the in-browser mock (VITE_MOCK=1).
import { GATEWAY_URL as LIVE_GATEWAY_URL, MOCK } from '../lib/config.js';

export const GATEWAY_URL = MOCK ? 'https://mcpbridge.dev' : LIVE_GATEWAY_URL;
export const SERVICE_UUID = '11111111-1111-1111-1111-111111111111';
export const mcpUrl = (uuid) => GATEWAY_URL + '/mcp/' + uuid;

/* ------------------------------------------- Demo Bistro connector manifest */
export const ORDER_SCHEMA = { $ref: '#/components/schemas/Order' };
export const MANIFEST = {
  manifestVersion: '1.0',
  publisher: {
    name: 'Demo Bistro', domain: 'demobistro.test',
    description: 'Neighborhood bistro with pickup and delivery. Search the menu, place orders and check on them.',
    category: 'food_and_drink', logoUrl: 'https://demobistro.test/assets/logo-512.png',
    privacyPolicyUrl: 'https://demobistro.test/privacy', termsUrl: 'https://demobistro.test/terms',
    contactEmail: 'alexa@demobistro.test'
  },
  accountLinking: {
    type: 'oauth2_authorization_code',
    authorizationUrl: 'https://auth.demobistro.test/authorize',
    tokenUrl: 'https://auth.demobistro.test/token',
    revocationUrl: 'https://auth.demobistro.test/revoke',
    clientId: 'mcpbridge', tokenAuthMethod: 'client_secret_post',
    scopes: ['read', 'order'], pkce: true
  },
  private: {
    clientSecret: 'REPLACE_WITH_CLIENT_SECRET',
    testAccount: { username: 'reviewer@demobistro.test', password: 'REPLACE_WITH_TEST_PASSWORD' },
    reviewNotes: 'The test account has order A1042 out for delivery, so get_order_status has something to find.'
  },
  openapi: {
    openapi: '3.1.0',
    info: { title: 'Demo Bistro API', version: '1.0.0', description: 'Menu search, ordering and order status for Demo Bistro.' },
    servers: [{ url: 'https://api.demobistro.test' }],
    security: [{ bistroOAuth: ['read', 'order'] }],
    paths: {
      '/menu/search': { get: {
        operationId: 'search_menu', summary: 'Search the menu',
        description: "Find dishes on the Demo Bistro menu by keyword, such as 'wrap' or 'vegan'. Returns matching dish names and prices.",
        parameters: [{ name: 'query', in: 'query', required: true, description: "Keyword to match against dish names and tags, e.g. 'wrap'", schema: { type: 'string', maxLength: 60 } }],
        responses: { 200: { description: 'Matching dishes', content: { 'application/json': { schema: { type: 'object', properties: { count: { type: 'integer' }, items: { type: 'array', items: { $ref: '#/components/schemas/MenuItem' } } }, required: ['count', 'items'] } } } } },
        'x-alexa': { examplePhrases: ["what's on the menu at Demo Bistro", 'does Demo Bistro have anything vegan', 'what wraps does Demo Bistro have'], sideEffect: 'none', requiresConfirmation: false, speakableResponse: 'I found {count} dishes, including {list:items.name}.', emptyResponse: "I couldn't find any dishes matching that." }
      } },
      '/orders/{order_id}': { get: {
        operationId: 'get_order_status', summary: 'Check an order',
        description: 'Get the status of an order by its ID.',
        parameters: [{ name: 'order_id', in: 'path', required: true, description: 'Order ID, e.g. A1042', schema: { type: 'string' } }],
        responses: { 200: { description: 'Order', content: { 'application/json': { schema: ORDER_SCHEMA } } }, 404: { description: 'Order not found' } },
        'x-alexa': { examplePhrases: ['what is the status of order A1042 at Demo Bistro', 'where is my Demo Bistro order'], sideEffect: 'none', requiresConfirmation: false, speakableResponse: 'Order {order_id} is {status_label}. It should be with you in about {eta_minutes} minutes.', errorResponses: { 404: "I couldn't find that order on your Demo Bistro account." } }
      } },
      '/orders': { post: {
        operationId: 'place_order', summary: 'Place an order',
        description: "Place a delivery or pickup order, charged to the card saved on the user's Demo Bistro account.",
        requestBody: { required: true, content: { 'application/json': { schema: { $ref: '#/components/schemas/NewOrder' } } } },
        responses: { 201: { description: 'Order placed', content: { 'application/json': { schema: ORDER_SCHEMA } } }, 409: { description: 'An item is sold out' } },
        'x-alexa': { examplePhrases: ['order a paneer wrap from Demo Bistro', 'get me two mango lassis from Demo Bistro for pickup'], sideEffect: 'payment', requiresConfirmation: true, confirmationPrompt: 'Should I place this {fulfillment} order with Demo Bistro? It will be charged to your saved card.', speakableResponse: 'Done. Order {order_id} comes to {total_formatted} and should be with you in about {eta_minutes} minutes.', errorResponses: { 409: 'Sorry, something in that order is sold out right now.' } }
      } }
    },
    components: {
      securitySchemes: { bistroOAuth: { type: 'oauth2', flows: { authorizationCode: { authorizationUrl: 'https://auth.demobistro.test/authorize', tokenUrl: 'https://auth.demobistro.test/token', refreshUrl: 'https://auth.demobistro.test/token', scopes: { read: 'See the menu and your orders', order: 'Place orders for you' } } } } },
      schemas: {
        MenuItem: { type: 'object', properties: { id: { type: 'string' }, name: { type: 'string' }, category: { type: 'string' }, price_cents: { type: 'integer' }, tags: { type: 'array', items: { type: 'string' } }, sold_out: { type: 'boolean' } }, required: ['id', 'name', 'price_cents'] },
        NewOrder: { type: 'object', properties: { items: { type: 'array', minItems: 1, maxItems: 10, description: 'Dishes to order.', items: { type: 'object', properties: { item_name: { type: 'string', description: 'Dish name as it appears on the menu.' }, quantity: { type: 'integer', minimum: 1, maximum: 10, default: 1 } }, required: ['item_name'] } }, fulfillment: { type: 'string', enum: ['delivery', 'pickup'], default: 'delivery', description: 'Delivery to the saved address, or pickup.' } }, required: ['items'] },
        Order: { type: 'object', properties: { order_id: { type: 'string' }, status: { type: 'string', enum: ['received', 'preparing', 'out_for_delivery', 'ready_for_pickup', 'delivered'] }, status_label: { type: 'string' }, fulfillment: { type: 'string', enum: ['delivery', 'pickup'] }, total_cents: { type: 'integer' }, total_formatted: { type: 'string' }, eta_minutes: { type: 'integer' } }, required: ['order_id', 'status', 'status_label'] }
      }
    }
  }
};
export const SCOPE_LABELS = { read: 'See the menu and your orders', order: 'Place orders for you' };
