import assert from 'node:assert/strict';
import { test } from 'node:test';
import { canCreateRun, createBlockReason, DEFAULT_LIMITS } from '../src/console.ts';
import { buildRunRequest, emptyForm, formFromRun, pickDevice } from '../src/form.ts';
import { changedOptionCount, DEVICE_POLL_MS, nextDevicePoll, rerunPlan, rerunServiceBlock, startNotices } from '../src/start.ts';

const ready = {
  configured: true, provider_key_configured: true, configuration_error: null, model: 'model-a', models: ['model-a', 'model-b'],
  active_run_id: null, execution_available: true, default_limits: DEFAULT_LIMITS, cleanup_attention_run_ids: [],
};
const device = { platform: 'android', serial: 'device-A', state: 'device', model: null, product: null, selectable: true };
const run = {
  run_id: 'run-1', device_id: 'device-A',
  goal: { text: 'Open Pantry Notes and add an item', expected_result: 'The item is listed', constraints: ['No payments'] },
  configuration: { limits: { ...DEFAULT_LIMITS, max_actions: 20 }, capabilities: [], identity: { provider: 'p', model: 'model-b', instruction_version: 'v1' } },
};

test('startNotices is empty when ready', () => {
  assert.deepEqual(startNotices(ready, true), []);
});

test('an unreachable service is one blocked notice with the block reason', () => {
  assert.deepEqual(startNotices(null, false), [{ tone: 'blocked', text: createBlockReason(null, false), action: null }]);
});

test('a missing provider key points to settings', () => {
  const notices = startNotices({ ...ready, provider_key_configured: false, configured: false }, true);
  assert.equal(notices.length, 1);
  assert.equal(notices[0].tone, 'blocked');
  assert.deepEqual(notices[0].action, { label: 'Open settings', target: 'settings' });
});

test('an open run points to that run', () => {
  const notices = startNotices({ ...ready, active_run_id: 'run-9', execution_available: false }, true);
  assert.equal(notices.length, 1);
  assert.equal(notices[0].tone, 'blocked');
  assert.deepEqual(notices[0].action, { label: 'View open run', target: 'run', runId: 'run-9' });
});

test('cleanup attention is a non-blocking warning', () => {
  const state = { ...ready, cleanup_attention_run_ids: ['run-3', 'run-4'] };
  const notices = startNotices(state, true);
  assert.equal(notices.length, 1);
  assert.equal(notices[0].tone, 'warning');
  assert.deepEqual(notices[0].action, { label: 'View run', target: 'run', runId: 'run-3' });
  assert.equal(canCreateRun(state, true), true);
});

test('changedOptionCount counts only options the operator changed', () => {
  const base = emptyForm(DEFAULT_LIMITS);
  assert.equal(changedOptionCount(base, DEFAULT_LIMITS, 'model-a'), 0);
  assert.equal(changedOptionCount({ ...base, expectedResult: 'Item listed' }, DEFAULT_LIMITS, null), 1);
  assert.equal(changedOptionCount({ ...base, expectedResult: 'x', constraints: ['No payments'], observeOnly: true }, DEFAULT_LIMITS, null), 3);
  assert.equal(changedOptionCount({ ...base, expectedResult: '  ', constraints: ['  '] }, DEFAULT_LIMITS, null), 0);
  assert.equal(changedOptionCount({ ...base, model: 'model-a' }, DEFAULT_LIMITS, 'model-a'), 0);
  assert.equal(changedOptionCount({ ...base, model: 'model-b' }, DEFAULT_LIMITS, 'model-a'), 1);
  assert.equal(changedOptionCount({ ...base, model: 'model-b' }, DEFAULT_LIMITS, null), 1);
  assert.equal(changedOptionCount({ ...base, limits: { ...base.limits, max_actions: '10' } }, DEFAULT_LIMITS, null), 1);
  assert.equal(changedOptionCount({ ...base, limits: { ...base.limits, max_actions: '60' } }, DEFAULT_LIMITS, null), 0);
});

test('changedOptionCount counts an unsaved constraint draft, since Start sends it', () => {
  const base = emptyForm(DEFAULT_LIMITS);
  assert.equal(changedOptionCount(base, DEFAULT_LIMITS, null), 0);
  assert.equal(changedOptionCount(base, DEFAULT_LIMITS, null, 'No payments'), 1);
  assert.equal(changedOptionCount(base, DEFAULT_LIMITS, null, '   '), 0);
  // Added constraints and a draft are one changed option together.
  assert.equal(changedOptionCount({ ...base, constraints: ['No payments'] }, DEFAULT_LIMITS, null, 'No sign-out'), 1);
});

test('rerunPlan creates with the same settings', () => {
  const plan = rerunPlan(run, [device], ready, true, DEFAULT_LIMITS);
  const form = pickDevice(formFromRun(run, ready.models, DEFAULT_LIMITS), 'device-A', [device]);
  assert.equal(plan.kind, 'create');
  assert.deepEqual(plan.request, buildRunRequest(form).request);
  assert.equal(plan.request.model, 'model-b');
  assert.equal(plan.request.observe_only, true);
  assert.equal(plan.request.limits.max_actions, 20);
  assert.equal(plan.request.platform, 'android');
});

test('rerunPlan allows a blank stored model (server default)', () => {
  const stored = { ...run, configuration: { ...run.configuration, identity: { ...run.configuration.identity, model: '' } } };
  const plan = rerunPlan(stored, [device], ready, true, DEFAULT_LIMITS);
  assert.equal(plan.kind, 'create');
  assert.equal(plan.request.model, null);
});

test('rerunPlan blocks a missing or unselectable device', () => {
  const reason = 'The device used by this run is not ready. Use Edit and rerun to pick another one.';
  assert.deepEqual(rerunPlan(run, [], ready, true, DEFAULT_LIMITS), { kind: 'blocked', reason });
  assert.deepEqual(rerunPlan(run, [{ ...device, selectable: false }], ready, true, DEFAULT_LIMITS), { kind: 'blocked', reason });
});

test('rerunPlan blocks a model no longer offered', () => {
  const plan = rerunPlan(run, [device], { ...ready, models: ['model-a'] }, true, DEFAULT_LIMITS);
  assert.deepEqual(plan, { kind: 'blocked', reason: 'The AI model used by this run is no longer offered. Use Edit and rerun to choose one.' });
});

test('rerunPlan blocks when the service cannot start runs', () => {
  assert.deepEqual(rerunPlan(run, [device], null, false, DEFAULT_LIMITS), { kind: 'blocked', reason: createBlockReason(null, false) });
  const busy = { ...ready, active_run_id: 'run-9' };
  assert.deepEqual(rerunPlan(run, [device], busy, true, DEFAULT_LIMITS), { kind: 'blocked', reason: createBlockReason(busy, true) });
});

test('rerunServiceBlock gives the service reason before any device listing', () => {
  assert.equal(rerunServiceBlock(ready, true), null);
  assert.equal(rerunServiceBlock(null, false), createBlockReason(null, false));
  assert.equal(rerunServiceBlock(ready, false), createBlockReason(ready, false));
  const busy = { ...ready, active_run_id: 'run-9' };
  assert.equal(rerunServiceBlock(busy, true), createBlockReason(busy, true));
  assert.equal(rerunServiceBlock({ ...ready, execution_available: false }, true), 'The service is not accepting new runs right now.');
});

test('rerunPlan reports the first request validation error', () => {
  const bad = { ...run, goal: { ...run.goal, text: '   ' } };
  const plan = rerunPlan(bad, [device], ready, true, DEFAULT_LIMITS);
  assert.equal(plan.kind, 'blocked');
  assert.equal(plan.reason, 'Describe what the AI should test.');
});

test('nextDevicePoll polls only while no device is selectable, no run is open and the page is visible', () => {
  assert.equal(DEVICE_POLL_MS, 5000);
  assert.equal(nextDevicePoll({ selectableCount: 0, runOpen: false, pageVisible: true }), 5000);
  assert.equal(nextDevicePoll({ selectableCount: 1, runOpen: false, pageVisible: true }), null);
  assert.equal(nextDevicePoll({ selectableCount: 0, runOpen: true, pageVisible: true }), null);
  assert.equal(nextDevicePoll({ selectableCount: 0, runOpen: false, pageVisible: false }), null);
});

test('nextDevicePoll keeps its interval after a failed list (callers pass selectableCount 0)', () => {
  assert.equal(nextDevicePoll({ selectableCount: 0, runOpen: false, pageVisible: true }), DEVICE_POLL_MS);
});
