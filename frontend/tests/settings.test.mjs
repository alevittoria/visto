import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  deleteKey, iosEdited, parseKeyStatus, parseSettings, parseVerify, saveSettings, setKey, settingsBody, settingsFromHash,
  verifyKey, verifyMessage,
} from '../src/settings.ts';

const base = { price_refresh: true, ios_supported: false, ios: null,
  key: { configured: false, last4: null, storage: 'file' }, wda_project: null, wda_rebuild_needed: false };
const ios = { team_id: 'TEAM123', signing_id: 'Dev', wda_bundle_id: 'com.example.wda', prebuilt_wda: false, wda_derived_data: '' };

function fakeFetch(calls, body, status = 200) {
  return async (url, init) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  };
}

test('settings view parsing hides iOS when unsupported', () => {
  assert.deepEqual(parseSettings(base), base);
  assert.equal(parseSettings({ ...base, ios_supported: false, ios: { team_id: 'x' } }), null);
  assert.equal(parseSettings({ ...base, key: { configured: true, last4: 'toolong', storage: 'file' } }), null);
});

test('settings view parsing accepts complete iOS values and rejects partial ones', () => {
  const supported = { ...base, ios_supported: true, ios, wda_project: '/opt/wda', wda_rebuild_needed: true };
  assert.deepEqual(parseSettings(supported), supported);
  assert.equal(parseSettings({ ...supported, ios: { ...ios, prebuilt_wda: 'no' } }), null);
  assert.equal(parseSettings({ ...supported, ios: null }), null);
  assert.equal(parseSettings({ ...base, price_refresh: 'yes' }), null);
  assert.equal(parseKeyStatus({ configured: true, last4: '1234', storage: 'file' })?.last4, '1234');
  assert.equal(parseKeyStatus({ configured: true, last4: '1234', storage: 'memory' }), null);
});

test('settings hash route', () => {
  assert.equal(settingsFromHash('#settings'), true);
  assert.equal(settingsFromHash('#run/abc'), false);
});

test('verify results have operator messages', () => {
  for (const r of ['ok', 'missing', 'unauthorized', 'model_unavailable', 'unreachable']) assert.ok(verifyMessage(r).length > 0);
  assert.equal(parseVerify({ result: 'maybe' }), null);
  assert.equal(parseVerify({ result: 'ok' }), 'ok');
});

test('setKey sends the key only in the body of a local write', async () => {
  const calls = []; await setKey('sk-test-1', fakeFetch(calls, { configured: true, last4: 'st-1', storage: 'file' }));
  assert.equal(calls[0].init.method, 'PUT'); assert.equal(calls[0].init.headers['X-Visto'], 'local-console');
  assert.ok(!calls[0].url.includes('sk-test-1'));
  assert.deepEqual(JSON.parse(calls[0].init.body), { api_key: 'sk-test-1' });
});

test('key removal, verification and saving use the settings routes', async () => {
  const calls = [];
  await deleteKey(fakeFetch(calls, { configured: false, last4: null, storage: 'file' }));
  assert.deepEqual([calls[0].url, calls[0].init.method], ['/api/settings/key', 'DELETE']);
  assert.equal(await verifyKey(fakeFetch(calls, { result: 'unauthorized' })), 'unauthorized');
  assert.deepEqual([calls[1].url, calls[1].init.method], ['/api/settings/key/verify', 'POST']);
  await saveSettings({ price_refresh: false, ios: null }, fakeFetch(calls, base));
  assert.deepEqual([calls[2].url, calls[2].init.method], ['/api/settings', 'PUT']);
  await assert.rejects(verifyKey(fakeFetch([], { result: 'maybe' })));
});

test('iOS values are sent only when the user edited them', () => {
  const supported = { ...base, ios_supported: true, ios, wda_rebuild_needed: true };
  assert.equal(iosEdited(ios, { ...ios }), false);
  assert.deepEqual(settingsBody(supported, false, { ...ios }), { price_refresh: false, ios: null });
  assert.deepEqual(settingsBody(supported, true, { ...ios, team_id: 'OTHER' }), { price_refresh: true, ios: { ...ios, team_id: 'OTHER' } });
  assert.deepEqual(settingsBody(base, true, null), { price_refresh: true, ios: null });
});
