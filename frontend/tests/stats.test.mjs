import assert from 'node:assert/strict';
import { test } from 'node:test';
import { formatUsd, parsePriceInfo, parseRunCost, parseStatistics, passShare, runCostText, statsFromHash } from '../src/stats.ts';

const outcomes = { passed: 2, failed: 1, inconclusive: 0, infrastructure_failure: 1, cancelled: 0, budget_exhausted: 0, unfinished: 0 };
const group = (extra = {}) => ({
  key: 'all', label: 'All runs', runs: 4, outcomes, ai_conclusions: 3, duration_ms: null, actions: null,
  input_tokens: 3_000_000, output_tokens: 200_000, unknown_usage_decisions: 0,
  tokens_by_model: { 'model-a': { input_tokens: 2_000_000, output_tokens: 100_000 }, 'model-b': { input_tokens: 1_000_000, output_tokens: 100_000 } },
  cost: { usd: 1.5, unpriced_runs: 1, unpriced_models: ['model-b'], approximate_runs: 0 },
  ...extra,
});

test('statistics are accepted only with complete counts', () => {
  const valid = { overall: group(), by_model: [group()], by_scenario: [group({ recent: [{ run_id: 'r1', outcome: 'passed' }] })] };
  assert.deepEqual(parseStatistics(valid), valid);
  assert.equal(parseStatistics({ ...valid, overall: group({ runs: -1 }) }), null);
  assert.equal(parseStatistics({ ...valid, by_model: [group({ outcomes: { ...outcomes, passed: undefined } })] }), null);
  assert.equal(parseStatistics({ ...valid, by_scenario: [group({ recent: [{ run_id: 'r1', outcome: 'great' }] })] }), null);
  assert.equal(parseStatistics({ ...valid, overall: group({ cost: { ...group().cost, usd: -1 } }) }), null);
  assert.equal(parseStatistics({ ...valid, overall: group({ cost: undefined }) }), null);
  assert.equal(parseStatistics(null), null);
});

test('price info requires an https source and numeric rates', () => {
  const info = { source: 'Source', source_url: 'https://example.invalid/p.json', attribution: 'Prices: Source', refresh_enabled: true,
    snapshot: { day: '2026-10-17', fetched_at: 't', source_updated_at: null }, error: null,
    models: { 'model-a': { day: '2026-10-17', input_per_m: 0.1, output_per_m: 0.5 } } };
  assert.deepEqual(parsePriceInfo(info), info);
  assert.equal(parsePriceInfo({ ...info, source_url: 'http://example.invalid' }), null);
  assert.equal(parsePriceInfo({ ...info, models: { m: { day: 'd', input_per_m: 'x', output_per_m: 1 } } }), null);
  assert.equal(parsePriceInfo(null), null);
  assert.equal(formatUsd(0.004), '$0.0040');
  assert.equal(formatUsd(0.0437), '$0.044');
  assert.equal(formatUsd(0), '$0.00');
  assert.equal(formatUsd(4), '$4.00');
});

test('pass share counts only AI conclusions and the stats route is exact', () => {
  assert.equal(passShare(group()), '2 / 3');
  assert.equal(passShare(group({ ai_conclusions: 0 })), null);
  assert.equal(statsFromHash('#stats'), true);
  assert.equal(statsFromHash('#run=stats'), false);
});

test('run cost shows the list day, approximation and unpriced runs honestly', () => {
  const priced = { usd: 0.0042, approximate: false, price_day: '2026-10-17', input_per_m: 0.1, output_per_m: 0.5 };
  assert.deepEqual(runCostText(parseRunCost(priced)), { text: '$0.0042', title: 'Price list of 2026-10-17: $0.1/1M input, $0.5/1M output' });
  assert.equal(runCostText(parseRunCost({ ...priced, usd: 2, approximate: true })).text, '≈ $2.00');
  const unpriced = { usd: null, approximate: false, price_day: null, input_per_m: null, output_per_m: null };
  assert.equal(runCostText(parseRunCost(unpriced)).text, 'No price yet');
  assert.equal(runCostText(parseRunCost({ ...priced, usd: -1 })).text, 'unknown');
  assert.equal(runCostText(parseRunCost(undefined)).text, 'unknown');
});
