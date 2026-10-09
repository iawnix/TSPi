import assert from 'node:assert/strict';
import { EventEmitter, once } from 'node:events';
import { request } from 'node:http';
import test from 'node:test';
import { createBrowserGateway } from '../../../apps/app-server/tspi-browser-gateway.mjs';

async function fixture(t) {
  const peer = new EventEmitter();
  const calls = [];
  peer.request = async (...args) => { calls.push(args); return { accepted: true }; };
  peer.isClosed = () => false;
  const identity = { workspace_id: 'ws_test', session_id: 'session-test' };
  const server = createBrowserGateway({ peer, identity, authToken: 'test-token' });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const port = server.address().port;
  const rpc = (body, headers = {}, path = '/rpc') => new Promise((resolve, reject) => {
    const req = request({ hostname: '127.0.0.1', port, path, method: 'POST', headers: {
      authorization: 'Bearer test-token', 'content-type': 'application/json', ...headers,
    } }, res => { let data = ''; res.on('data', chunk => { data += chunk; }); res.on('end', () => resolve({ status: res.statusCode, body: JSON.parse(data) })); });
    req.on('error', reject); req.end(JSON.stringify(body));
  });
  return { rpc, calls, port, identity };
}

test('gateway requires authentication and rejects cross-origin, rebound Host and non-JSON writes', async t => {
  assert.throws(() => createBrowserGateway({}), /auth token/);
  const { rpc, calls } = await fixture(t);
  const body = { id: 'same-input', method: 'input/send', params: { text: 'hello', client_message_id: 'message-1' } };
  for (const [headers, status] of [
    [{ authorization: '' }, 401], [{ authorization: 'Bearer wrong' }, 401],
    [{ origin: 'https://evil.example' }, 403], [{ host: 'evil.example' }, 403],
    [{ 'content-type': 'text/plain' }, 415],
  ]) assert.equal((await rpc(body, headers)).status, status);
  assert.equal(calls.length, 0);
});

test('gateway has one request format, fixed session and caller-owned mutation identity', async t => {
  const { rpc, calls, port, identity } = await fixture(t);
  for (const body of [
    { action: 'prompt', message: 'old', request_id: 'old' },
    { method: 'input/send', params: { text: 'missing identity' } },
    { method: 'workspace/create' },
  ]) assert.equal((await rpc(body)).status, 400);
  assert.equal((await rpc({ method: 'session/read', params: { session_id: 'another' } })).status, 403);
  const body = { id: 'stable', method: 'input/send', params: { text: 'hello', client_message_id: 'message-1' } };
  assert.equal((await rpc(body, { origin: `http://127.0.0.1:${port}` })).status, 200);
  assert.equal((await rpc(body)).status, 200);
  assert.deepEqual(calls, Array.from({ length: 2 }, () => ['input/send', { ...body.params, ...identity, request_id: 'stable' }]));
  assert.equal((await rpc(body, {}, '/requests')).status, 404);
});
