import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DEFAULT_LIMITS } from '../src/console.ts';
import { applyDefaultLimits, buildRunRequest, emptyForm, formFromRun, LIMIT_FIELDS } from '../src/form.ts';

const valid = () => ({ ...emptyForm(DEFAULT_LIMITS), deviceId: ' emulator-5554 ', goal: '  Open Sample Notes\nand check the list  ' });

test('form defaults show time limits in seconds and produce contract default limits', () => {
  const form = emptyForm(DEFAULT_LIMITS);
  assert.equal(form.limits.wall_time_ms, '1200');
  assert.equal(form.limits.max_actions, '60');
  const { request } = buildRunRequest(valid());
  assert.deepEqual(request.limits, DEFAULT_LIMITS);
});

test('request preserves goal text verbatim, trims serial, drops blank optional values', () => {
  const { request, errors } = buildRunRequest({ ...valid(), expectedResult: '   ', constraints: ['No payments', '  ', 'Synthetic data only'], observeOnly: true });
  assert.equal(errors, null);
  assert.deepEqual(request, {
    device_id: 'emulator-5554', model: null, goal: '  Open Sample Notes\nand check the list  ', expected_result: null,
    constraints: ['No payments', 'Synthetic data only'], observe_only: true, limits: DEFAULT_LIMITS,
  });
});

test('required fields and text bounds are validated with plain messages', () => {
  const { request, errors } = buildRunRequest({ ...emptyForm(DEFAULT_LIMITS), goal: ' \n ' });
  assert.equal(request, null);
  assert.ok(errors.deviceId && errors.goal);
  assert.ok(buildRunRequest({ ...valid(), goal: 'x'.repeat(16001) }).errors.goal);
  assert.equal(buildRunRequest({ ...valid(), goal: '\u{1F600}'.repeat(16000) }).errors, null, 'code points, not UTF-16 units');
  assert.ok(buildRunRequest({ ...valid(), expectedResult: 'x'.repeat(8001) }).errors.expectedResult);
  assert.ok(buildRunRequest({ ...valid(), constraints: Array(33).fill('c') }).errors.constraints);
  assert.ok(buildRunRequest({ ...valid(), constraints: ['x'.repeat(2001)] }).errors.constraints);
  assert.ok(buildRunRequest({ ...valid(), deviceId: 'd'.repeat(257) }).errors.deviceId);
});

test('limits are bounded per contract and converted from seconds to milliseconds', () => {
  const withLimit = (key, value) => buildRunRequest({ ...valid(), limits: { ...valid().limits, [key]: value } });
  assert.equal(withLimit('wall_time_ms', '3600').request.limits.wall_time_ms, 3600000);
  assert.equal(withLimit('wall_time_ms', '0.5').request.limits.wall_time_ms, 500);
  assert.ok(withLimit('wall_time_ms', '3601').errors.wall_time_ms);
  assert.ok(withLimit('wall_time_ms', '0').errors.wall_time_ms);
  assert.ok(withLimit('max_command_timeout_ms', '61').errors.max_command_timeout_ms);
  assert.equal(withLimit('max_observation_delay_ms', '60').request.limits.max_observation_delay_ms, 60000);
  assert.ok(withLimit('max_actions', '301').errors.max_actions);
  assert.ok(withLimit('max_actions', '2.5').errors.max_actions);
  assert.ok(withLimit('max_inferences', '-1').errors.max_inferences);
  assert.ok(withLimit('max_inferences', 'abc').errors.max_inferences);
  assert.ok(withLimit('max_inferences', '').errors.max_inferences);
  assert.equal(LIMIT_FIELDS.length, 5);
});

test('server defaults replace only limits the operator has not edited', () => {
  const form = { ...emptyForm(DEFAULT_LIMITS) };
  form.limits = { ...form.limits, max_actions: '7' };
  const next = { ...DEFAULT_LIMITS, max_actions: 40, wall_time_ms: 120000 };
  const updated = applyDefaultLimits(form, DEFAULT_LIMITS, next);
  assert.equal(updated.limits.max_actions, '7');
  assert.equal(updated.limits.wall_time_ms, '120');
});

test('selected model is sent trimmed; blank uses the server default', () => {
  assert.equal(buildRunRequest({ ...valid(), model: ' gpt-6-luna ' }).request.model, 'gpt-6-luna');
  assert.equal(buildRunRequest({ ...valid(), model: '' }).request.model, null);
});

test('run again prefills goal, model, mode and limits from a stored run', () => {
  const limits = { ...DEFAULT_LIMITS, wall_time_ms: 90000, max_actions: 12 };
  const run = {
    device_id: 'emulator-5554',
    goal: { text: 'Open Sample Notes', expected_result: 'The demo note is listed', constraints: ['No payments'] },
    configuration: { limits, capabilities: [], identity: { provider: 'openai', model: 'gpt-6-sol', instruction_version: 'v' } },
  };
  const form = formFromRun(run, ['gpt-6-luna', 'gpt-6-sol'], DEFAULT_LIMITS);
  assert.equal(form.model, 'gpt-6-sol');
  assert.equal(form.observeOnly, true);
  assert.equal(form.limits.wall_time_ms, '90');
  const { request, errors } = buildRunRequest(form);
  assert.equal(errors, null);
  assert.deepEqual(request, {
    device_id: 'emulator-5554', model: 'gpt-6-sol', goal: 'Open Sample Notes', expected_result: 'The demo note is listed',
    constraints: ['No payments'], observe_only: true, limits,
  });
  form.constraints.push('changed');
  assert.deepEqual(run.goal.constraints, ['No payments'], 'stored run is not mutated');
});

test('run again drops a model no longer offered and keeps operating mode', () => {
  const run = {
    device_id: 'd', goal: { text: 'g', expected_result: null, constraints: [] },
    configuration: { limits: DEFAULT_LIMITS, capabilities: ['tap'], identity: { provider: 'p', model: 'retired', instruction_version: 'v' } },
  };
  const form = formFromRun(run, ['gpt-6-luna'], DEFAULT_LIMITS);
  assert.equal(form.model, '');
  assert.equal(form.observeOnly, false);
  assert.equal(form.expectedResult, '');
});
