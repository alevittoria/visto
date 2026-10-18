import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  actionMarker, buildHistory, cleanupWarning, describeCommand, latestDecision, latestObservation, observationsById,
  outcomeExplanation, screenshotFreshness,
} from '../src/history.ts';

const obs = (n) => ({
  sequence: n, kind: 'observation',
  data: { kind: 'observation', observation_id: `o${n}`, run_id: 'r1', sequence: n, captured_at: `2026-10-16T10:00:0${n}+00:00`,
    width: 1080, height: 2400, rotation: 0,
    screenshot: { artifact_id: `a${n}`, run_id: 'r1', media_type: 'image/png', byte_length: 10, sha256: 'f'.repeat(64), url: `/api/runs/r1/artifacts/o${n}` } },
});
const decision = (n, plan, next, effect = null) => ({
  sequence: n, kind: 'agent_decision',
  data: { kind: 'agent_decision', decision_id: `d${n}`, run_id: 'r1', rationale: `why ${n}`, working_plan: plan,
    presented_observation_ids: ['o1'], source_observation_id: 'o1', previous_effect: effect, next,
    identity: { kind: 'model_identity', provider: 'p', model: 'm', instruction_version: 'v' }, usage: { kind: 'model_usage', input_tokens: null, output_tokens: 3 } },
});
const events = [
  obs(1),
  decision(2, '1. open app', { kind: 'act', command: { kind: 'tap', x: 10, y: 20 }, timeout_ms: 5000 }),
  { sequence: 3, kind: 'action', data: { kind: 'action', action_id: 'x1', run_id: 'r1', decision_id: 'd2', observation_id: 'o1', lease_id: 'l', command: { kind: 'tap', x: 10, y: 20 }, timeout_ms: 5000 } },
  { sequence: 4, kind: 'technical_receipt', data: { kind: 'technical_receipt', run_id: 'r1', action_id: 'x1', status: 'completed',
    dispatched_at: '2026-10-16T10:00:03+00:00', started_at: null, finished_at: '2026-10-16T10:00:04.500000+00:00', detail: '' } },
  obs(5),
  decision(6, '1. open app', { kind: 'ask_user', question: 'Which account?' },
    { kind: 'effect_assessment', action_id: 'x1', verdict: 'achieved', explanation: 'App opened', observation_ids: ['o5'] }),
  { sequence: 7, kind: 'pending_question', data: { kind: 'pending_question', question_id: 'q1', run_id: 'r1', decision_id: 'd6', question: 'Which account?', created_at: '2026-10-16T10:00:06+00:00', answer: null, cancelled_at: null } },
  { sequence: 8, kind: 'user_answer', data: { kind: 'user_answer', question_id: 'q1', run_id: 'r1', text: 'Test user', answered_by: 'web-operator', answered_at: '2026-10-16T10:00:07+00:00' } },
  decision(9, '1. open app\n2. sign in', { kind: 'conclude', assessment: { kind: 'assessment', run_id: 'r1', decision_id: 'd9', verdict: 'passed', explanation: 'ok', observation_ids: ['o5'] } }),
];

test('events map to chronological typed entries regardless of arrival order', () => {
  const entries = buildHistory([...events].reverse(), 'r1');
  assert.deepEqual(entries.map((e) => e.type), ['observation', 'decision', 'action', 'receipt', 'observation', 'decision', 'question', 'answer', 'decision']);
  assert.equal(entries[0].url, '/api/runs/r1/artifacts/o1');
  assert.equal(entries[4].index, 2);
  assert.equal(entries[2].description, 'Tap at (10, 20)');
  assert.equal(entries[7].text, 'Test user');
});

test('technical receipts are labelled as technical, never as test success', () => {
  const receipt = buildHistory(events, 'r1').find((e) => e.type === 'receipt');
  assert.equal(receipt.status, 'completed');
  assert.match(receipt.label, /technical/i);
  assert.doesNotMatch(receipt.label, /pass|success/i);
  assert.equal(receipt.durationMs, 1500);
});

test('working plan changes are detected; effect assessments and next steps are carried', () => {
  const decisions = buildHistory(events, 'r1').filter((e) => e.type === 'decision');
  assert.deepEqual(decisions.map((d) => d.planChanged), [true, false, true]);
  assert.equal(decisions[1].effect.verdict, 'achieved');
  assert.match(decisions[1].next, /Which account/);
  assert.equal(decisions[2].next, 'Concluded: AI passed');
});

test('latest observation and decision selection, and lookup by id', () => {
  const entries = buildHistory(events, 'r1');
  assert.equal(latestObservation(entries).id, 'o5');
  assert.equal(latestDecision(entries).id, 'd9');
  assert.equal(latestObservation([]), null);
  assert.equal(latestDecision(buildHistory([obs(1)], 'r1')), null);
  assert.equal(observationsById(entries).get('o1').index, 1);
});

test('unsafe screenshot links are dropped and unknown record kinds are kept as unknown', () => {
  const bad = obs(1);
  bad.data.screenshot.url = 'https://evil.example/x.png';
  const entries = buildHistory([bad, { sequence: 2, kind: 'future_kind', data: {} }], 'r1');
  assert.equal(entries[0].url, null);
  assert.deepEqual(entries[1], { type: 'unknown', sequence: 2, kind: 'future_kind' });
});

test('commands are described in plain language', () => {
  assert.equal(describeCommand({ kind: 'back' }), 'Press Back');
  assert.equal(describeCommand({ kind: 'home' }), 'Go to the Home screen');
  assert.equal(describeCommand({ kind: 'type_text', text: 'abc' }), 'Type “abc”');
  assert.match(describeCommand({ kind: 'swipe', start_x: 1, start_y: 2, end_x: 3, end_y: 4, duration_ms: 300 }), /Swipe from \(1, 2\) to \(3, 4\) over 300 ms/);
});

const base = { run_id: 'r1', device_id: 'dev', revision: 1, state: 'running', terminal: null, interrupted: false, control_pending: null, can_resume: false, pending_question: null };

test('screenshot is marked stale unless the run is active and updates are connected', () => {
  assert.equal(screenshotFreshness(base, true).current, true);
  assert.match(screenshotFreshness(base, true).label, /not a live view/);
  assert.equal(screenshotFreshness(base, false).current, false);
  assert.equal(screenshotFreshness({ ...base, state: 'paused' }, true).current, false);
  assert.equal(screenshotFreshness({ ...base, interrupted: true }, true).current, false);
  assert.equal(screenshotFreshness({ ...base, state: 'terminal' }, true).current, false);
});

test('outcome explanations separate AI verdicts from technical endings', () => {
  const end = (terminal) => outcomeExplanation({ ...base, state: 'terminal', terminal });
  assert.match(end({ kind: 'ai_conclusion', assessment: { verdict: 'failed' } }), /AI concluded the test failed/);
  assert.match(end({ kind: 'ai_conclusion', assessment: { verdict: 'inconclusive' } }), /inconclusive/);
  for (const terminal of [{ kind: 'infrastructure_failure' }, { kind: 'cancelled' }, { kind: 'budget_exhausted', budget: 'actions' }]) {
    assert.match(end(terminal), /not a test verdict/);
  }
  assert.match(outcomeExplanation({ ...base, interrupted: true }), /cannot be controlled here/);
});

test('cleanup failure is a separate warning that never changes the outcome', () => {
  assert.equal(cleanupWarning(base), null);
  const run = { ...base, state: 'terminal', terminal: { kind: 'ai_conclusion', assessment: { verdict: 'passed' } }, cleanup_failed: true };
  assert.match(cleanupWarning(run), /check device dev/);
  assert.match(outcomeExplanation(run), /concluded the test passed/);
});

test('pointer commands carry overlay geometry; key and text commands do not', () => {
  assert.deepEqual(actionMarker({ kind: 'tap', x: 10, y: 20 }), { kind: 'point', x: 10, y: 20, long: false });
  assert.deepEqual(actionMarker({ kind: 'long_press', x: 5, y: 6, duration_ms: 900 }), { kind: 'point', x: 5, y: 6, long: true });
  assert.deepEqual(actionMarker({ kind: 'swipe', start_x: 1, start_y: 2, end_x: 3, end_y: 4, duration_ms: 300 }),
    { kind: 'line', x1: 1, y1: 2, x2: 3, y2: 4 });
  for (const command of [{ kind: 'enter' }, { kind: 'back' }, { kind: 'type_text', text: 'x' }, { kind: 'tap', x: 'a', y: 1 }, undefined]) {
    assert.equal(actionMarker(command), null);
  }
  assert.equal(describeCommand({ kind: 'long_press', x: 5, y: 6, duration_ms: 900 }), 'Long press at (5, 6) for 900 ms');
  assert.equal(describeCommand({ kind: 'enter' }), 'Press Enter');
  const entries = buildHistory(events, 'r1');
  assert.deepEqual(entries[2].marker, { kind: 'point', x: 10, y: 20, long: false });
});
