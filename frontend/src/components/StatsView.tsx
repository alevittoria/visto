import { useCallback, useEffect, useState } from 'react';
import { apiRequest, formatTokens } from '../console.ts';
import { formatDuration, formatTime } from '../history.ts';
import { formatUsd, OUTCOME_LABELS, OUTCOMES, parsePriceInfo, parseStatistics, passShare } from '../stats.ts';
import type { PriceInfo, Statistics, StatsGroup } from '../stats.ts';

interface Props { onOpenRun: (runId: string) => void }

type Grouping = 'model' | 'scenario';

export function StatsView({ onOpenRun }: Props) {
  const [stats, setStats] = useState<Statistics | null>(null);
  const [prices, setPrices] = useState<PriceInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [grouping, setGrouping] = useState<Grouping>('model');

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const [parsed, priceInfo] = await Promise.all([
        apiRequest<unknown>('/statistics', { signal }).then(parseStatistics),
        apiRequest<unknown>('/prices', { signal }).then(parsePriceInfo, () => null),
      ]);
      if (signal?.aborted) return;
      if (!parsed) throw new Error('Invalid statistics');
      setStats(parsed);
      setPrices(priceInfo);
      setError(null);
    } catch {
      if (signal?.aborted) return;
      setError('Statistics could not be loaded.');
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const groups = stats ? (grouping === 'model' ? stats.by_model : stats.by_scenario) : [];

  return (
    <section className="stats" aria-labelledby="stats-title">
      <div className="panel">
        <div className="card-heading">
          <h1 id="stats-title">Run statistics</h1>
          <button type="button" className="secondary small" onClick={() => void load()} disabled={loading}>{loading ? 'Loading…' : 'Refresh'}</button>
        </div>
        <p className="lead">Outcomes repeat each stored run’s own result; nothing is re-judged. These are counts of what happened, not a labelled
          evaluation: a pass is the AI’s conclusion, not proof that it was right. Durations run from creation to the end and include paused time.</p>
        {error && <p className="error-text" role="alert">{error} <button type="button" className="link" onClick={() => void load()}>Retry</button></p>}
        {stats && <Summary group={stats.overall} />}
      </div>

      {stats && stats.overall.runs > 0 && (
        <div className="panel">
          <div className="card-heading">
            <h2>Compare</h2>
            <div className="segmented" role="group" aria-label="Group runs by">
              <button type="button" className="secondary small" aria-pressed={grouping === 'model'} onClick={() => setGrouping('model')}>By model</button>
              <button type="button" className="secondary small" aria-pressed={grouping === 'scenario'} onClick={() => setGrouping('scenario')}>By scenario</button>
            </div>
          </div>
          {grouping === 'scenario' && <p className="help">A scenario is one exact goal with the same expected result and constraints. Repeat a run with “Run again” to add to it.</p>}
          {grouping === 'model'
            ? <ModelTable groups={groups} />
            : <ul className="scenario-list">{groups.map((group) => <Scenario key={group.key} group={group} onOpenRun={onOpenRun} />)}</ul>}
        </div>
      )}

      <PricePanel prices={prices} />
    </section>
  );
}

function OutcomeBadges({ group }: { group: StatsGroup }) {
  return (
    <span className="outcome-badges">
      {OUTCOMES.filter((name) => group.outcomes[name] > 0).map((name) => (
        <span key={name} className={`badge ${OUTCOME_LABELS[name].tone}`}>{OUTCOME_LABELS[name].label} {group.outcomes[name]}</span>
      ))}
    </span>
  );
}

function Cost({ group }: { group: StatsGroup }) {
  const { cost } = group;
  if (cost.unpriced_runs === group.runs && group.runs > 0 && cost.usd === 0) {
    return <span className="muted" title={`No price for ${cost.unpriced_models.join(', ')}`}>No price yet</span>;
  }
  const notes = [
    cost.unpriced_runs > 0 ? `${cost.unpriced_runs} unpriced run(s): ${cost.unpriced_models.join(', ')}` : null,
    cost.approximate_runs > 0 ? `${cost.approximate_runs} run(s) older than the first stored price list use it as an approximation` : null,
  ].filter(Boolean).join('; ');
  return (
    <span title={notes || undefined}>
      {cost.approximate_runs > 0 ? '≈ ' : ''}{formatUsd(cost.usd)}
      {cost.unpriced_runs > 0 && <span className="muted"> + unpriced</span>}
    </span>
  );
}

function spreadText(spread: StatsGroup['duration_ms'], format: (value: number) => string): string {
  if (!spread) return '—';
  return spread.min === spread.max ? format(spread.median) : `${format(spread.median)} (${format(spread.min)}–${format(spread.max)})`;
}

const actionsText = (value: number) => String(value);

function Summary({ group }: { group: StatsGroup }) {
  if (group.runs === 0) return <p className="muted">No stored runs yet.</p>;
  return (
    <>
      <OutcomeBadges group={group} />
      <dl className="facts">
        <div><dt>Runs</dt><dd>{group.runs}</dd></div>
        <div><dt>AI passed / AI conclusions</dt><dd>{passShare(group) ?? '—'}</dd></div>
        <div><dt>Duration, median (range)</dt><dd>{spreadText(group.duration_ms, formatDuration)}</dd></div>
        <div><dt>Actions, median (range)</dt><dd>{spreadText(group.actions, actionsText)}</dd></div>
        <div><dt>Input tokens</dt><dd>{formatTokens(group.input_tokens)}</dd></div>
        <div><dt>Output tokens</dt><dd>{formatTokens(group.output_tokens)}</dd></div>
        <div><dt>Estimated cost</dt><dd><Cost group={group} /></dd></div>
      </dl>
      {group.unknown_usage_decisions > 0 && <p className="help">{group.unknown_usage_decisions} AI steps did not report usage and are not counted.</p>}
      {group.cost.approximate_runs > 0 && (
        <p className="help">{group.cost.approximate_runs} run(s) predate the first stored price list and are priced with it (marked ≈).</p>
      )}
    </>
  );
}

function ModelTable({ groups }: { groups: StatsGroup[] }) {
  return (
    <div className="table-scroll">
      <table className="stats-table">
        <thead>
          <tr>
            <th scope="col">Model</th><th scope="col">Runs</th><th scope="col">Outcomes</th><th scope="col">AI passed</th>
            <th scope="col">Median duration</th><th scope="col">Median actions</th><th scope="col">Tokens in / out</th><th scope="col">Est. cost</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <tr key={group.key}>
              <th scope="row"><code>{group.label}</code></th>
              <td>{group.runs}</td>
              <td><OutcomeBadges group={group} /></td>
              <td>{passShare(group) ?? '—'}</td>
              <td>{group.duration_ms ? formatDuration(group.duration_ms.median) : '—'}</td>
              <td>{group.actions ? group.actions.median : '—'}</td>
              <td>{formatTokens(group.input_tokens)} / {formatTokens(group.output_tokens)}</td>
              <td><Cost group={group} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Scenario({ group, onOpenRun }: { group: StatsGroup; onOpenRun: (runId: string) => void }) {
  const recent = group.recent ?? [];
  return (
    <li className="scenario">
      <p className="scenario-goal">{group.label}</p>
      {group.expected_result && <p className="help">Expected: {group.expected_result}</p>}
      {group.constraints && group.constraints.length > 0 && <p className="help">Constraints: {group.constraints.join(' · ')}</p>}
      <dl className="facts compact">
        <div><dt>Runs</dt><dd>{group.runs}</dd></div>
        <div><dt>AI passed</dt><dd>{passShare(group) ?? '—'}</dd></div>
        <div><dt>Median duration</dt><dd>{group.duration_ms ? formatDuration(group.duration_ms.median) : '—'}</dd></div>
        <div><dt>Median actions</dt><dd>{group.actions ? group.actions.median : '—'}</dd></div>
        <div><dt>Tokens in / out</dt><dd>{formatTokens(group.input_tokens)} / {formatTokens(group.output_tokens)}</dd></div>
        <div><dt>Est. cost</dt><dd><Cost group={group} /></dd></div>
      </dl>
      <ol className="run-strip" aria-label="Runs of this scenario, newest first">
        {recent.map((run) => {
          const badge = OUTCOME_LABELS[run.outcome];
          const cost = run.cost_usd === null ? 'unpriced' : `${run.cost_approximate ? '≈ ' : ''}${formatUsd(run.cost_usd)}`;
          const detail = [run.model, formatTime(run.created_at), run.duration_ms === null ? null : formatDuration(run.duration_ms), `${run.actions} actions`, cost]
            .filter(Boolean).join(' · ');
          return (
            <li key={run.run_id}>
              <a className={`badge ${badge.tone}`} href={`#run=${run.run_id}`} title={detail}
                onClick={(event) => { event.preventDefault(); onOpenRun(run.run_id); }}>
                {badge.label}<span className="visually-hidden"> — {detail}</span>
              </a>
            </li>
          );
        })}
        {group.runs > recent.length && <li className="muted small-text">+{group.runs - recent.length} older</li>}
      </ol>
    </li>
  );
}

function PricePanel({ prices }: { prices: PriceInfo | null }) {
  const models = prices ? Object.entries(prices.models) : [];
  return (
    <details className="panel prices">
      <summary>Prices used for the cost estimate</summary>
      {!prices && <p className="muted small-text">Price information is not available from the service.</p>}
      {prices && (
        <>
          <p className="help">
            The service stores one public price list per day (UTC) and prices each run with the list in effect on the day it was created,
            so older runs keep their own day’s prices. Base input/output rates in USD per one million tokens; cached-input and
            long-context discounts or surcharges are not distinguished. {prices.refresh_enabled
              ? 'The list is fetched at service start and checked hourly.'
              : 'Automatic refresh is turned off on this service.'}
          </p>
          {prices.snapshot
            ? <p className="small-text">Latest list: {prices.snapshot.day}{prices.snapshot.source_updated_at ? ` (source updated ${formatTime(prices.snapshot.source_updated_at)})` : ''}.</p>
            : <p className="small-text muted">No price list stored yet.</p>}
          {prices.error && <p className="error-text small-text" role="status">{prices.error}</p>}
          {models.length > 0 && (
            <div className="table-scroll">
              <table className="stats-table">
                <thead><tr><th scope="col">Model</th><th scope="col">Input $/1M</th><th scope="col">Output $/1M</th><th scope="col">List day</th></tr></thead>
                <tbody>
                  {models.map(([model, price]) => (
                    <tr key={model}><th scope="row"><code>{model}</code></th><td>{price.input_per_m}</td><td>{price.output_per_m}</td><td>{price.day}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="fine-print">{prices.attribution} <a href="https://www.aipricing.guru/" target="_blank" rel="noreferrer noopener">{prices.source}</a></p>
        </>
      )}
    </details>
  );
}
