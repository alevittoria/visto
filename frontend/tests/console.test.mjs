import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  answerRecordedText, apiRequest, canCreateRun, controlAvailability, createBlockReason, createRunMonitor, DEFAULT_LIMITS, isUncertain,
  outcome, parseReadiness, pollDelay, runIdFromHash, safeScreenshotUrl, shouldResumeAfterAnswer,
} from '../src/console.ts';

const response = (body, status = 200) => new Response(JSON.stringify(body), { status });
const run = { run_id: 'r1', revision: 1, state: 'running', terminal: null };

test('creation requires configured, available readiness and a connected service', () => {
  const ready = { configured: true, execution_available: true };
  assert.equal(canCreateRun(ready, true), true);
  assert.equal(canCreateRun(ready, false), false);
  assert.equal(canCreateRun({ ...ready, configured: false }, true), false);
  assert.equal(canCreateRun({ ...ready, execution_available: false }, true), false);
  assert.equal(canCreateRun(null, true), false);
});

test('API mutations include same-origin header, reads never mutate or cache', async () => {
  const requests = [];
  const fetcher = async (url, options) => { requests.push([url, options]); return response(run); };
  await apiRequest('/runs', { method: 'POST', body: { goal: 'Original goal' } }, fetcher);
  await apiRequest('/runs/r1', {}, fetcher);
  assert.equal(requests[0][0], '/api/runs');
  assert.equal(requests[0][1].headers['X-Visto'], 'local-console');
  assert.equal(requests[0][1].body, '{"goal":"Original goal"}');
  assert.equal(requests[1][1].method, 'GET');
  assert.equal(requests[1][1].cache, 'no-store');
});

test('API failures expose safe contract detail but never unknown response bodies', async () => {
  await assert.rejects(apiRequest('/runs', {}, async () => response({ detail: 'Run is busy' }, 409)), /Run is busy/);
  await assert.rejects(apiRequest('/runs', {}, async () => response({ private: 'secret' }, 500)), /^Error: Request failed \(HTTP 500\)$/);
  await assert.rejects(apiRequest('/runs', {}, async () => { throw new Error('private network detail'); }), /Connection lost/);
});

test('terminal distinctions come only from stored AI or technical records', () => {
  for (const verdict of ['passed', 'failed', 'inconclusive']) {
    assert.equal(outcome({ ...run, state: 'terminal', terminal: { kind: 'ai_conclusion', assessment: { verdict } } }).label, `AI ${verdict}`);
  }
  assert.equal(outcome({ ...run, state: 'terminal', terminal: { kind: 'infrastructure_failure' } }).label, 'Infrastructure failure');
  assert.equal(outcome({ ...run, state: 'terminal', terminal: { kind: 'cancelled' } }).label, 'Cancelled');
  assert.equal(outcome({ ...run, state: 'terminal', terminal: { kind: 'budget_exhausted' } }).label, 'Budget exhausted');
  assert.equal(outcome(run).label, 'Running');
});

test('screenshots are accepted only from the current scoped observation route', () => {
  assert.equal(safeScreenshotUrl('/api/runs/r1/artifacts/o1', 'r1'), '/api/runs/r1/artifacts/o1');
  for (const value of ['https://example.com/image', '/api/runs/r2/artifacts/o1', '/api/runs/r1/artifacts/../other', 'javascript:alert(1)']) {
    assert.equal(safeScreenshotUrl(value, 'r1'), null);
  }
});

test('monitor consumes incremental events, deduplicates and recovers without resetting evidence', async () => {
  const calls = [];
  let attempt = 0;
  const snapshots = [];
  const monitor = createRunMonitor('r1', (state) => snapshots.push(state), async (path) => {
    calls.push(path);
    if (path.endsWith('/r1')) return run;
    attempt += 1;
    if (attempt === 2) throw new Error('offline');
    return attempt === 1 ? { events: [{ sequence: 1, kind: 'observation', data: {} }], next_after: 1 }
      : { events: [{ sequence: 1, kind: 'observation', data: {} }, { sequence: 2, kind: 'action', data: {} }], next_after: 2 };
  });
  await monitor.refresh();
  await monitor.refresh();
  assert.equal(snapshots.at(-1).connected, false);
  assert.equal(snapshots.at(-1).events.length, 1);
  await monitor.refresh();
  assert.equal(snapshots.at(-1).connected, true);
  assert.deepEqual(snapshots.at(-1).events.map((event) => event.sequence), [1, 2]);
  assert.ok(calls.includes('/runs/r1/events?after=1&limit=100'));
  monitor.dispose();
});

test('disposed monitor ignores late run and event completions', async () => {
  const pending = [];
  const snapshots = [];
  const monitor = createRunMonitor('r1', (state) => snapshots.push(state), () => new Promise((resolve) => pending.push(resolve)));
  const work = monitor.refresh();
  monitor.dispose();
  pending.forEach((resolve, index) => resolve(index === 0 ? run : { events: [], next_after: 0 }));
  await work;
  assert.equal(snapshots.length, 0);
});

test('mutation errors distinguish definite rejections from uncertain outcomes', async () => {
  const reject = async (fetcher) => { try { await apiRequest('/runs', { method: 'POST', body: {} }, fetcher); } catch (error) { return error; } };
  const definite = await reject(async () => response({ detail: 'Invalid request fields: goal, limits.wall_time_ms' }, 422));
  assert.equal(definite.message, 'Invalid request fields: goal, limits.wall_time_ms');
  assert.equal(isUncertain(definite), false);
  assert.equal(isUncertain(await reject(async () => response({ detail: 'busy' }, 409))), false);
  assert.equal(isUncertain(await reject(async () => { throw new TypeError('network'); })), true);
  assert.equal(isUncertain(await reject(async () => new Response('<html>', { status: 502 }))), true);
  assert.equal(isUncertain(await reject(async () => response({ detail: 'proxy' }, 504))), true);
  assert.equal(isUncertain(await reject(async () => response({ other: 1 }, 400))), true);
  assert.equal(isUncertain(await reject(async () => response({ detail: 'Local evidence storage is unavailable' }, 503))), true);
});

test('readiness parsing validates the contract and defaults new optional lists', () => {
  const ready = { configured: true, provider_key_configured: true, configuration_error: null, model: 'm', appium_url: 'http://127.0.0.1:4723',
    device_selection: 'manual', devices: [], active_run_id: null, execution_available: true, default_limits: DEFAULT_LIMITS };
  assert.deepEqual(parseReadiness(ready).cleanup_attention_run_ids, []);
  assert.deepEqual(parseReadiness({ ...ready, cleanup_attention_run_ids: ['r9', 3] }).cleanup_attention_run_ids, ['r9']);
  for (const invalid of [null, [], { ...ready, configured: 'yes' }, { ...ready, default_limits: { ...DEFAULT_LIMITS, max_actions: '20' } }]) {
    assert.throws(() => parseReadiness(invalid), /Invalid readiness/);
  }
});

test('create block reasons are plain and ordered by what the operator must fix first', () => {
  const ready = { configured: true, provider_key_configured: true, configuration_error: null, execution_available: true, active_run_id: null };
  assert.equal(createBlockReason(ready, true), null);
  assert.match(createBlockReason(ready, false), /not reachable/);
  assert.match(createBlockReason({ ...ready, configured: false, provider_key_configured: false }, true), /No AI provider key/);
  assert.match(createBlockReason({ ...ready, configured: false, configuration_error: 'Bad settings' }, true), /Bad settings/);
  assert.match(createBlockReason({ ...ready, active_run_id: 'r1', execution_available: false }, true), /Another run/);
  assert.match(createBlockReason({ ...ready, execution_available: false }, true), /not accepting/);
});

const view = { ...run, interrupted: false, control_pending: null, can_resume: false, pending_question: null };
const question = { question_id: 'q1', answer: null, cancelled_at: null };

test('controls follow stored lifecycle and block during uncertainty or disconnection', () => {
  assert.deepEqual(controlAvailability(view, true, false, false), { pause: true, resume: false, cancel: true, answer: false });
  const none = { pause: false, resume: false, cancel: false, answer: false };
  assert.deepEqual(controlAvailability(view, false, false, false), none);
  assert.deepEqual(controlAvailability(view, true, true, false), none);
  assert.deepEqual(controlAvailability(view, true, false, true), none);
  assert.deepEqual(controlAvailability({ ...view, interrupted: true }, true, false, false), none);
  assert.deepEqual(controlAvailability({ ...view, state: 'terminal', terminal: { kind: 'cancelled' } }, true, false, false), none);
  assert.deepEqual(controlAvailability({ ...view, state: 'paused', can_resume: true }, true, false, false), { pause: false, resume: true, cancel: true, answer: false });
  assert.equal(controlAvailability({ ...view, control_pending: 'pause' }, true, false, false).pause, false);
  assert.equal(controlAvailability({ ...view, control_pending: 'cancel' }, true, false, false).cancel, false);
  const waiting = { ...view, state: 'waiting_for_user', pending_question: question };
  assert.deepEqual(controlAvailability(waiting, true, false, false), { pause: false, resume: false, cancel: true, answer: true });
  assert.equal(controlAvailability({ ...waiting, pending_question: { ...question, answer: { text: 'x' } }, can_resume: true }, true, false, false).answer, false);
});

test('polling runs while active, backs off when disconnected and stops when ended', () => {
  const snap = (value, connected = true) => ({ run: value, events: [], connected, error: null, checkedAt: 1 });
  assert.equal(pollDelay(snap(view), 0), 1000);
  assert.equal(pollDelay(snap({ ...view, state: 'paused' }), 0), 2000);
  assert.equal(pollDelay(snap({ ...view, state: 'paused', control_pending: 'resume' }), 0), 1000);
  assert.equal(pollDelay(snap({ ...view, state: 'terminal' }), 0), null);
  assert.equal(pollDelay(snap({ ...view, interrupted: true }), 0), null);
  assert.equal(pollDelay(snap(view, false), 1), 2000);
  assert.equal(pollDelay(snap(view, false), 10), 10000);
});

test('monitor pages through full event pages and re-reads once after a terminal run', async () => {
  const calls = [];
  const page = (from, count) => Array.from({ length: count }, (_, i) => ({ sequence: from + i + 1, kind: 'observation', data: {} }));
  let last;
  const tracked = createRunMonitor('r1', (s) => { last = s; }, async (path) => {
    calls.push(path);
    if (path.endsWith('/r1')) return { ...run, state: 'terminal', terminal: { kind: 'cancelled' } };
    const after = Number(/after=(\d+)/.exec(path)[1]);
    const count = after === 0 ? 100 : after === 100 ? 20 : 0;
    return { events: page(after, count), next_after: after + count };
  });
  assert.equal(await tracked.refresh(), true);
  assert.equal(last.events.length, 120);
  assert.deepEqual(calls.filter((p) => p.includes('events')), [
    '/runs/r1/events?after=0&limit=100', '/runs/r1/events?after=100&limit=100', '/runs/r1/events?after=120&limit=100']);
  tracked.dispose();
});

test('selected run comes only from a safe hash identifier', () => {
  assert.equal(runIdFromHash('#run=abc-123_x.y'), 'abc-123_x.y');
  for (const hash of ['', '#run=', '#run=../x', '#run=a/b', '#other=abc']) assert.equal(runIdFromHash(hash), null);
});

test('readiness models fall back to the default model and reconcile keeps a valid choice', async () => {
  const { parseReadiness, reconcileModel } = await import('../src/console.ts');
  const base = { configured: true, provider_key_configured: true, execution_available: true, configuration_error: null,
    model: 'gpt-6-sol', appium_url: null, active_run_id: null, default_limits: DEFAULT_LIMITS };
  const readiness = parseReadiness({ ...base, models: ['gpt-6-sol', 'gpt-5.6-terra', 'gpt-6-luna', 7, ' '] });
  assert.deepEqual(readiness.models, ['gpt-6-sol', 'gpt-5.6-terra', 'gpt-6-luna']);
  assert.equal(reconcileModel('gpt-6-luna', readiness), 'gpt-6-luna');
  assert.equal(reconcileModel('', readiness), 'gpt-6-sol');
  assert.deepEqual(parseReadiness(base).models, ['gpt-6-sol']);
});

test('token usage parsing rejects malformed counts and only non-owned runs are deletable', async () => {
  const { canDeleteRun, parseUsage } = await import('../src/console.ts');
  const usage = { input_tokens: 3000, output_tokens: 120, recorded_decisions: 2, unknown_usage_decisions: 0 };
  assert.deepEqual(parseUsage(usage), usage);
  assert.equal(parseUsage({ ...usage, input_tokens: -1 }), null);
  assert.equal(parseUsage(null), null);
  const run = (state, interrupted = false) => ({ run_id: 'r1', state, interrupted });
  assert.equal(canDeleteRun(run('terminal'), null), true);
  assert.equal(canDeleteRun(run('running'), 'r1'), false);
  assert.equal(canDeleteRun(run('paused', true), null), true);
  assert.equal(canDeleteRun(run('terminal'), 'r1'), false);
});

test('resume after an answer follows the refreshed run, and the answer response only when the refresh failed', () => {
  const resumable = { run_id: 'r1', can_resume: true };
  const notResumable = { run_id: 'r1', can_resume: false };
  assert.equal(shouldResumeAfterAnswer(notResumable, resumable), true);
  assert.equal(shouldResumeAfterAnswer(resumable, notResumable), false);
  assert.equal(shouldResumeAfterAnswer(resumable, null), true);
  assert.equal(shouldResumeAfterAnswer(notResumable, null), false);
});

test('answerRecordedText matches the run state and mentions Resume only when it can be selected', () => {
  const base = { run_id: 'r1', state: 'waiting_for_user', interrupted: false, can_resume: false, control_pending: null };
  assert.equal(answerRecordedText({ ...base, state: 'terminal' }), 'Answer recorded; the run has ended.');
  assert.equal(answerRecordedText({ ...base, state: 'paused', interrupted: true }), 'Answer recorded; the run has ended.');
  assert.equal(answerRecordedText({ ...base, control_pending: 'cancel' }), 'Answer recorded; the run is being cancelled.');
  assert.equal(answerRecordedText({ ...base, state: 'running' }), 'Answer recorded; the run is already running.');
  assert.equal(answerRecordedText({ ...base, state: 'created' }), 'Answer recorded; the run is already running.');
  assert.equal(answerRecordedText({ ...base, can_resume: true }), 'Answer recorded. Select Resume to let the AI continue.');
  assert.doesNotMatch(answerRecordedText(base), /Select Resume/);
});
