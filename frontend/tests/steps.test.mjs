import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildHistory, observationsById } from '../src/history.ts';
import { currentStepNumber, groupSteps } from '../src/steps.ts';

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
const action = (n, id) => ({ sequence: n, kind: 'action', data: { kind: 'action', action_id: id, run_id: 'r1', decision_id: 'd', observation_id: 'o1', lease_id: 'l', command: { kind: 'tap', x: 10, y: 20 }, timeout_ms: 5000 } });
const receipt = (n, id, status = 'completed') => ({ sequence: n, kind: 'technical_receipt', data: { kind: 'technical_receipt', run_id: 'r1', action_id: id, status,
  dispatched_at: '2026-10-16T10:00:03+00:00', started_at: null, finished_at: '2026-10-16T10:00:04+00:00', detail: '' } });
const act = { kind: 'act', command: { kind: 'tap', x: 10, y: 20 }, timeout_ms: 5000 };
const effect = (id, verdict = 'achieved', explanation = 'App opened') => ({ kind: 'effect_assessment', action_id: id, verdict, explanation, observation_ids: ['o5'] });
const conclude = { kind: 'conclude', assessment: { kind: 'assessment', run_id: 'r1', decision_id: 'd9', verdict: 'passed', explanation: 'ok', observation_ids: ['o5'] } };

const events = [
  obs(1),
  decision(2, 'plan', act),
  action(3, 'x1'),
  receipt(4, 'x1'),
  obs(5),
  decision(6, 'plan', { kind: 'ask_user', question: 'Which account?' }, effect('x1')),
  { sequence: 7, kind: 'pending_question', data: { kind: 'pending_question', question_id: 'q1', run_id: 'r1', decision_id: 'd6', question: 'Which account?', created_at: '2026-10-16T10:00:06+00:00', answer: null, cancelled_at: null } },
  { sequence: 8, kind: 'user_answer', data: { kind: 'user_answer', question_id: 'q1', run_id: 'r1', text: 'Test user', answered_by: 'web-operator', answered_at: '2026-10-16T10:00:07+00:00' } },
  decision(9, 'plan', conclude),
];

const group = (evts) => {
  const entries = buildHistory(evts, 'r1');
  return { entries, steps: groupSteps(entries, observationsById(entries)) };
};

test('groupSteps assigns each record to the decision that precedes it', () => {
  const { steps } = group(events);
  assert.equal(steps.length, 3);
  assert.deepEqual(steps[0].records.map((r) => r.type), ['observation', 'decision', 'action', 'receipt', 'observation']);
  assert.deepEqual(steps[1].records.map((r) => r.type), ['decision', 'question', 'answer']);
  assert.deepEqual(steps.map((s) => s.number), [1, 2, 3]);
  assert.equal(steps[0].action.id, 'x1');
  assert.equal(steps[0].receipt.status, 'completed');
  assert.equal(steps[0].summary, 'Tap at (10, 20)');
  assert.equal(steps[0].thumbnail.id, 'o1');
  assert.equal(currentStepNumber(steps), 3);
});

test('effect comes from the next decision', () => {
  const { steps } = group(events);
  assert.equal(steps[0].effect, 'achieved');
  assert.equal(steps[0].effectExplanation, 'App opened');
  assert.equal(steps[2].effect, 'none');
  assert.equal(steps[2].effectExplanation, null);
});

test('latest action awaits judgement', () => {
  const { steps } = group(events.slice(0, 4));
  assert.equal(steps.length, 1);
  assert.equal(steps[0].effect, 'pending');
  assert.equal(steps[0].effectExplanation, null);
});

test('non-action decisions get a row', () => {
  const { steps } = group([
    obs(1),
    decision(2, 'p', { kind: 'observe_after', delay_ms: 1000 }),
    decision(3, 'p', { kind: 'ask_user', question: 'q?' }),
    decision(4, 'p', conclude),
  ]);
  assert.deepEqual(steps.map((s) => s.summary), ['Wait and look again', 'Asked a question', 'Concluded']);
  assert.ok(steps.every((s) => s.effect === 'none'));
});

test('rejected or uncertain receipt replaces the effect', () => {
  for (const status of ['rejected', 'uncertain']) {
    const { steps } = group([obs(1), decision(2, 'p', act), action(3, 'x1'), receipt(4, 'x1', status),
      decision(5, 'p', conclude, effect('x1'))]);
    assert.equal(steps[0].effect, 'none');
    assert.equal(steps[0].receipt.status, status);
  }
});

test('groupSteps handles observations before any decision', () => {
  const { entries, steps } = group([obs(1)]);
  assert.equal(steps.length, 1);
  assert.equal(steps[0].number, 1);
  assert.equal(steps[0].decision, null);
  assert.equal(steps[0].summary, 'Waiting for the first AI step');
  assert.equal(steps[0].records.length, 1);
  assert.equal(currentStepNumber(steps), 0);
  assert.equal(entries.length, 1);
});

test('no record is dropped', () => {
  const { entries, steps } = group([...events, { sequence: 10, kind: 'future_kind', data: {} }]);
  assert.equal(steps.reduce((n, s) => n + s.records.length, 0), entries.length);
  assert.equal(groupSteps([], new Map()).length, 0);
  assert.equal(currentStepNumber([]), 0);
});

test('effect matches by action id', () => {
  const { steps } = group([obs(1), decision(2, 'p', act), action(3, 'x1'), receipt(4, 'x1'),
    decision(5, 'p', conclude, effect('other'))]);
  assert.equal(steps[0].effect, 'pending');
  assert.equal(steps[0].effectExplanation, null);
});
