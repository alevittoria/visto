import assert from 'node:assert/strict';
import { test } from 'node:test';
import { deviceLabel, parseDevices, reconcileDevice } from '../src/console.ts';

const ready = { platform: 'android', serial: 'SERIAL01', state: 'device', model: 'Example Phone 1', product: 'example_phone', selectable: true };
const pending = { platform: 'android', serial: 'emulator-5554', state: 'unauthorized', model: null, product: null, selectable: false };

test('device list parsing drops malformed or unsafe entries', () => {
  const parsed = parseDevices({ available: true, error: null, devices: [ready, pending, { platform: 'android', serial: '<b>x</b>', state: 'device', selectable: true }, null, { platform: 'android', state: 'device' }] });
  assert.deepEqual(parsed.devices.map((d) => d.serial), ['SERIAL01', 'emulator-5554']);
  assert.equal(parseDevices({ available: false, devices: [], error: 'adb was not found' }).error, 'adb was not found');
  assert.throws(() => parseDevices(null));
  // A device is selectable only when adb reports it ready.
  assert.equal(parseDevices({ devices: [{ ...pending, selectable: true }] }).devices[0].selectable, false);
});

test('refresh notes keep only strings and default to none', () => {
  assert.deepEqual(parseDevices({ available: true, devices: [], notes: ['xcrun was not found', 3, null] }).notes,
    ['xcrun was not found']);
  assert.deepEqual(parseDevices({ available: true, devices: [] }).notes, []);
});

test('labels name the model and explain why a device cannot be used', () => {
  assert.match(deviceLabel(ready), /^Example Phone 1 \(SERIAL01\)/);
  assert.match(deviceLabel(pending), /emulator-5554 · Android — not authorized/);
});

test('selection keeps a valid choice and preselects a single ready device', () => {
  assert.equal(reconcileDevice('', [ready, pending]), 'SERIAL01');
  assert.equal(reconcileDevice('SERIAL01', [ready]), 'SERIAL01');
  assert.equal(reconcileDevice('gone', [ready, { ...ready, serial: 'SERIAL02' }]), '');
  assert.equal(reconcileDevice('emulator-5554', [pending]), '');
  assert.equal(reconcileDevice('SERIAL01', []), '');
});

const sim = { platform: 'ios', serial: 'SIM-UDID-01', state: 'booted', model: 'Example Simulator', product: null, selectable: true };

test('entries carry a known platform or are dropped', () => {
  const parsed = parseDevices({ devices: [ready, sim, { ...ready, serial: 'S3', platform: 'symbian' }, { ...ready, serial: 'S4', platform: undefined }] });
  assert.deepEqual(parsed.devices.map((d) => [d.serial, d.platform]), [['SERIAL01', 'android'], ['SIM-UDID-01', 'ios']]);
});

test('selectability follows the platform vocabulary', () => {
  const pick = (d) => parseDevices({ devices: [d] }).devices[0];
  assert.equal(pick(ready).selectable, true);
  assert.equal(pick({ ...ready, state: 'booted' }).selectable, false, 'iOS words do not make an Android entry ready');
  assert.equal(pick(sim).selectable, true);
  assert.equal(pick({ ...sim, state: 'connected' }).selectable, true);
  assert.equal(pick({ ...sim, state: 'device' }).selectable, false, 'adb words do not make an iOS entry ready');
  assert.equal(pick({ ...sim, state: 'shutdown', selectable: true }).selectable, false);
  assert.equal(pick({ ...sim, state: 'unavailable', selectable: true }).selectable, false);
  assert.equal(pick({ ...sim, selectable: false }).selectable, false, 'the server flag is still required');
});

test('labels say which platform a device is', () => {
  assert.equal(deviceLabel(sim), 'Example Simulator (SIM-UDID-01) · iOS');
  assert.equal(deviceLabel(ready), 'Example Phone 1 (SERIAL01) · Android');
});

test('a shut-down simulator explains that it must be booted first', () => {
  const off = parseDevices({ devices: [{ ...sim, state: 'shutdown', selectable: false }] }).devices[0];
  assert.match(deviceLabel(off), /not booted: start the simulator from Xcode first/);
  const gone = parseDevices({ devices: [{ ...sim, state: 'unavailable', selectable: false }] }).devices[0];
  assert.match(deviceLabel(gone), /unavailable: /);
  assert.doesNotMatch(deviceLabel(gone), /— unavailable$/);
});
