import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHealthMonitor, loadHealth } from '../src/health.ts';

const healthy = { product: 'Visto', version: '0.1.0', runtime_ready: false };
const response = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});

test('loads health without treating backend availability as runtime readiness', async () => {
  const result = await loadHealth(async (url, options) => {
    assert.equal(url, '/api/health');
    assert.equal(options.cache, 'no-store');
    return response(healthy);
  });
  assert.deepEqual(result, healthy);
});

test('rejects HTTP errors, malformed JSON and invalid health contracts', async () => {
  await assert.rejects(loadHealth(async () => response({}, 503)), /HTTP 503/);
  await assert.rejects(loadHealth(async () => new Response('not json')), /Invalid health response/);
  for (const invalid of [null, [], {}, { ...healthy, runtime_ready: 'false' },
    { ...healthy, product: 'Another server' }, { ...healthy, version: '' }]) {
    await assert.rejects(loadHealth(async () => response(invalid)), /Invalid health response/);
  }
});

test('network errors produce a disconnected state without exposing error payloads', async () => {
  const states = [];
  const monitor = createHealthMonitor((state) => states.push(state), async () => {
    throw new Error('private upstream diagnostic');
  });
  await monitor.refresh();
  assert.deepEqual(states.map((state) => state.kind), ['checking', 'disconnected']);
  assert.equal(states[1].message, 'Cannot reach the local backend. Check that it is running, then refresh.');
  monitor.dispose();
});

test('only the newest refresh may publish, even when an older fetch ignores cancellation', async () => {
  const pending = [];
  const states = [];
  const monitor = createHealthMonitor((state) => states.push(state), () => new Promise((resolve) => {
    pending.push(resolve);
  }));
  const older = monitor.refresh();
  const newer = monitor.refresh();
  pending[1](response({ ...healthy, version: '0.2.0' }));
  await newer;
  pending[0](response(healthy));
  await older;
  assert.equal(states.length, 3);
  assert.equal(states[2].health.version, '0.2.0');
  monitor.dispose();
});

test('dispose aborts work and prevents late completion from publishing', async () => {
  const states = [];
  let complete;
  let signal;
  const monitor = createHealthMonitor((state) => states.push(state), (_url, options) => {
    signal = options.signal;
    return new Promise((resolve) => { complete = resolve; });
  });
  const work = monitor.refresh();
  monitor.dispose();
  assert.equal(signal.aborted, true);
  complete(response(healthy));
  await work;
  assert.equal(states.length, 1);
});

test('a request that exceeds its deadline becomes disconnected', async () => {
  const states = [];
  const monitor = createHealthMonitor((state) => states.push(state), (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true });
  }), 5);
  await monitor.refresh();
  assert.equal(states.at(-1).kind, 'disconnected');
  assert.equal(states.at(-1).message, 'The local backend did not respond in time. Refresh to try again.');
  monitor.dispose();
});
