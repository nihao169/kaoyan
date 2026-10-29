import { afterEach, test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { api, ApiError } from '../src/api.ts';

afterEach(() => mock.restoreAll());

test('empty proxy failure produces a readable service error', async () => {
  mock.method(globalThis, 'fetch', async () => new Response('', {status:500}));
  await assert.rejects(api('/me'), (e: unknown) => e instanceof ApiError && e.code==='SERVICE_UNAVAILABLE' && !e.message.includes('JSON'));
});

test('HTML gateway failure produces a readable service error', async () => {
  mock.method(globalThis, 'fetch', async () => new Response('<html>Bad Gateway</html>', {status:502}));
  await assert.rejects(api('/me'), (e: unknown) => e instanceof ApiError && e.code==='SERVICE_UNAVAILABLE');
});

test('network failure preserves a distinct retryable error', async () => {
  mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch'); });
  await assert.rejects(api('/me'), (e: unknown) => e instanceof ApiError && e.code==='NETWORK_ERROR');
});

test('malformed success and missing envelopes are rejected', async () => {
  for (const body of ['', 'null', '{}']) {
    mock.method(globalThis, 'fetch', async () => new Response(body));
    await assert.rejects(api('/me'), (e: unknown) => e instanceof ApiError && e.code==='INVALID_RESPONSE');
    mock.restoreAll();
  }
});

test('login error retains the server code and status', async () => {
  mock.method(globalThis, 'fetch', async () => Response.json({error:{code:'UNAUTHENTICATED',message:'请先登录'}},{status:401}));
  await assert.rejects(api('/me'), (e: unknown) => e instanceof ApiError && e.status===401 && e.code==='UNAUTHENTICATED');
});

test('valid responses retain data including null', async () => {
  for (const data of [null, {id:'saved-record'}]) {
    mock.method(globalThis, 'fetch', async () => Response.json({data}));
    assert.deepEqual(await api('/me'), data);
    mock.restoreAll();
  }
});
