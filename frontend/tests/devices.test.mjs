import assert from 'node:assert/strict';
import { test } from 'node:test';
import { deviceLabel, parseDevices, reconcileDevice } from '../src/console.ts';

const ready = { serial: 'SERIAL01', state: 'device', model: 'Example Phone 1', product: 'example_phone', selectable: true };
const pending = { serial: 'emulator-5554', state: 'unauthorized', model: null, product: null, selectable: false };

test('device list parsing drops malformed or unsafe entries', () => {
  const parsed = parseDevices({ available: true, error: null, devices: [ready, pending, { serial: '<b>x</b>', state: 'device', selectable: true }, null, { state: 'device' }] });
  assert.deepEqual(parsed.devices.map((d) => d.serial), ['SERIAL01', 'emulator-5554']);
  assert.equal(parseDevices({ available: false, devices: [], error: 'adb was not found' }).error, 'adb was not found');
  assert.throws(() => parseDevices(null));
  // A device is selectable only when adb reports it ready.
  assert.equal(parseDevices({ devices: [{ ...pending, selectable: true }] }).devices[0].selectable, false);
});

test('refresh notes keep only strings and default to none', () => {
  assert.deepEqual(parseDevices({ available: true, devices: [], notes: ['Host adb is not reachable', 3, null] }).notes,
    ['Host adb is not reachable']);
  assert.deepEqual(parseDevices({ available: true, devices: [] }).notes, []);
});

test('labels name the model and explain why a device cannot be used', () => {
  assert.equal(deviceLabel(ready), 'Example Phone 1 (SERIAL01)');
  assert.match(deviceLabel(pending), /emulator-5554 — not authorized/);
});

test('selection keeps a valid choice and preselects a single ready device', () => {
  assert.equal(reconcileDevice('', [ready, pending]), 'SERIAL01');
  assert.equal(reconcileDevice('SERIAL01', [ready]), 'SERIAL01');
  assert.equal(reconcileDevice('gone', [ready, { ...ready, serial: 'SERIAL02' }]), '');
  assert.equal(reconcileDevice('emulator-5554', [pending]), '');
  assert.equal(reconcileDevice('SERIAL01', []), '');
});
