/** Aggregates from GET /api/statistics, with costs priced by each run's creation day. */

export const OUTCOMES = ['passed', 'failed', 'inconclusive', 'infrastructure_failure', 'cancelled', 'budget_exhausted', 'unfinished'] as const;
export type Outcome = typeof OUTCOMES[number];

export const OUTCOME_LABELS: Record<Outcome, { label: string; tone: string }> = {
  passed: { label: 'AI passed', tone: 'success' },
  failed: { label: 'AI failed', tone: 'danger' },
  inconclusive: { label: 'AI inconclusive', tone: 'warning' },
  infrastructure_failure: { label: 'Infrastructure failure', tone: 'danger' },
  cancelled: { label: 'Cancelled', tone: 'warning' },
  budget_exhausted: { label: 'Budget exhausted', tone: 'warning' },
  unfinished: { label: 'Unfinished', tone: 'neutral' },
};

export interface Spread { mean: number; median: number; min: number; max: number }
export interface ModelTokens { input_tokens: number; output_tokens: number }

export interface RecentRun {
  run_id: string;
  outcome: Outcome;
  model: string;
  created_at: string;
  duration_ms: number | null;
  actions: number;
  cost_usd: number | null;
  cost_approximate: boolean;
}

/** Sum over priced runs; unpriced runs are counted and their models named, never guessed. */
export interface GroupCost { usd: number; unpriced_runs: number; unpriced_models: string[]; approximate_runs: number }

export interface StatsGroup {
  key: string;
  label: string;
  runs: number;
  outcomes: Record<Outcome, number>;
  ai_conclusions: number;
  duration_ms: Spread | null;
  actions: Spread | null;
  input_tokens: number;
  output_tokens: number;
  unknown_usage_decisions: number;
  tokens_by_model: Record<string, ModelTokens>;
  cost: GroupCost;
  expected_result?: string | null;
  constraints?: string[];
  recent?: RecentRun[];
}

export interface Statistics { overall: StatsGroup; by_model: StatsGroup[]; by_scenario: StatsGroup[] }

const count = (value: unknown) => Number.isSafeInteger(value) && (value as number) >= 0;
const usd = (value: unknown) => typeof value === 'number' && Number.isFinite(value) && value >= 0;

function validGroup(value: unknown): value is StatsGroup {
  const g = value as Partial<StatsGroup> | null;
  if (typeof g !== 'object' || g === null || typeof g.key !== 'string' || typeof g.label !== 'string') return false;
  if (![g.runs, g.ai_conclusions, g.input_tokens, g.output_tokens, g.unknown_usage_decisions].every(count)) return false;
  if (typeof g.outcomes !== 'object' || g.outcomes === null || !OUTCOMES.every((name) => count(g.outcomes![name]))) return false;
  if (typeof g.tokens_by_model !== 'object' || g.tokens_by_model === null) return false;
  if (!Object.values(g.tokens_by_model).every((t) => count(t?.input_tokens) && count(t?.output_tokens))) return false;
  const c = g.cost;
  if (typeof c !== 'object' || c === null || !usd(c.usd) || !count(c.unpriced_runs) || !count(c.approximate_runs)) return false;
  if (!Array.isArray(c.unpriced_models) || !c.unpriced_models.every((m) => typeof m === 'string')) return false;
  return g.recent === undefined || (Array.isArray(g.recent) && g.recent.every((r) => typeof r?.run_id === 'string' && OUTCOMES.includes(r.outcome)));
}

export function parseStatistics(value: unknown): Statistics | null {
  const v = value as Partial<Statistics> | null;
  if (typeof v !== 'object' || v === null || !validGroup(v.overall)) return null;
  if (!Array.isArray(v.by_model) || !Array.isArray(v.by_scenario)) return null;
  if (!v.by_model.every(validGroup) || !v.by_scenario.every(validGroup)) return null;
  return v as Statistics;
}

export function formatUsd(value: number): string {
  // Single runs cost fractions of a cent: keep enough digits to compare them.
  if (value > 0 && value < 0.01) return `$${value.toFixed(4)}`;
  if (value > 0 && value < 1) return `$${value.toFixed(3)}`;
  return `$${value.toFixed(2)}`;
}

export interface ModelPrice { day: string; input_per_m: number; output_per_m: number }

/** GET /api/prices: the latest stored daily snapshot; the console never fetches prices itself. */
export interface PriceInfo {
  source: string;
  source_url: string;
  attribution: string;
  refresh_enabled: boolean;
  snapshot: { day: string; fetched_at: string; source_updated_at: string | null } | null;
  error: string | null;
  models: Record<string, ModelPrice>;
}

export function parsePriceInfo(value: unknown): PriceInfo | null {
  const v = value as Partial<PriceInfo> | null;
  if (typeof v !== 'object' || v === null || typeof v.source !== 'string' || typeof v.attribution !== 'string') return null;
  if (typeof v.source_url !== 'string' || !v.source_url.startsWith('https://')) return null;
  if (typeof v.models !== 'object' || v.models === null) return null;
  const valid = Object.values(v.models).every((p) => typeof p?.day === 'string' && usd(p.input_per_m) && usd(p.output_per_m));
  if (!valid) return null;
  return { ...v, refresh_enabled: v.refresh_enabled === true, snapshot: v.snapshot ?? null, error: v.error ?? null } as PriceInfo;
}

/** GET /api/runs/{id} `cost`: priced with the list of the run's UTC creation day. */
export interface RunCost {
  usd: number | null;
  approximate: boolean;
  price_day: string | null;
  input_per_m: number | null;
  output_per_m: number | null;
}

export function parseRunCost(value: unknown): RunCost | null {
  const v = value as Partial<RunCost> | null;
  if (typeof v !== 'object' || v === null) return null;
  const optional = (x: unknown) => x === null || usd(x);
  if (!optional(v.usd) || !optional(v.input_per_m) || !optional(v.output_per_m)) return null;
  if (v.price_day !== null && typeof v.price_day !== 'string') return null;
  return { usd: v.usd!, approximate: v.approximate === true, price_day: v.price_day ?? null,
    input_per_m: v.input_per_m ?? null, output_per_m: v.output_per_m ?? null };
}

/** Display text and explanation for one run's estimated cost. */
export function runCostText(cost: RunCost | null): { text: string; title: string | undefined } {
  if (!cost) return { text: 'unknown', title: undefined };
  if (cost.usd === null) return { text: 'No price yet', title: 'No stored price list covers this model' };
  if (cost.price_day === null) return { text: formatUsd(cost.usd), title: undefined };
  const rates = `$${cost.input_per_m}/1M input, $${cost.output_per_m}/1M output`;
  return cost.approximate
    ? { text: `≈ ${formatUsd(cost.usd)}`, title: `Run predates the first stored price list; priced with the ${cost.price_day} list (${rates})` }
    : { text: formatUsd(cost.usd), title: `Price list of ${cost.price_day}: ${rates}` };
}

/** "passed / AI conclusions"; null when the AI concluded nothing in the group. */
export function passShare(group: StatsGroup): string | null {
  if (group.ai_conclusions === 0) return null;
  return `${group.outcomes.passed} / ${group.ai_conclusions}`;
}

export function statsFromHash(hash: string): boolean {
  return hash === '#stats';
}
