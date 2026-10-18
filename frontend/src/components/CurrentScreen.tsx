import type { Run } from '../console.ts';
import { EFFECT_LABELS, formatTime, screenshotFreshness } from '../history.ts';
import type { DecisionEntry, ObservationEntry } from '../history.ts';

export function CurrentScreen({ run, connected, entry }: { run: Run; connected: boolean; entry: ObservationEntry | null }) {
  const freshness = screenshotFreshness(run, connected);
  return (
    <section className="panel screen" aria-labelledby="screen-title">
      <div className="card-heading">
        <h2 id="screen-title">Device screen</h2>
        <span className={`badge ${freshness.current ? 'active' : 'stale'}`}>{freshness.label}</span>
      </div>
      {!entry && <p className="muted">{run.state === 'terminal' || run.interrupted ? 'No screenshot was recorded.' : 'Waiting for the first screenshot…'}</p>}
      {entry && (
        <figure className={freshness.current ? '' : 'is-stale'}>
          {entry.url
            ? <a href={entry.url} target="_blank" rel="noopener noreferrer"><img src={entry.url} alt={`Device screenshot ${entry.index}, captured ${formatTime(entry.capturedAt)}`} width={entry.width} height={entry.height} /></a>
            : <p className="error-text">This screenshot link was not accepted by the console.</p>}
          <figcaption>Screenshot {entry.index} · captured <time dateTime={entry.capturedAt}>{formatTime(entry.capturedAt)}</time></figcaption>
        </figure>
      )}
    </section>
  );
}

export function LatestThinking({ entry }: { entry: DecisionEntry | null }) {
  return (
    <section className="panel thinking" aria-labelledby="thinking-title">
      <h2 id="thinking-title">AI reasoning</h2>
      {!entry && <p className="muted">The AI has not made a decision yet.</p>}
      {entry && (
        <>
          {entry.effect && (
            <div className={`effect ${entry.effect.verdict}`}>
              <h3>Effect of the previous action</h3>
              <p><strong>{EFFECT_LABELS[entry.effect.verdict] ?? entry.effect.verdict}.</strong> {entry.effect.explanation}</p>
            </div>
          )}
          <h3>Why</h3>
          <p className="prewrap">{entry.rationale}</p>
          <h3>Working plan{entry.planChanged ? <span className="badge neutral small">Updated</span> : null}</h3>
          <p className="prewrap">{entry.workingPlan.trim() ? entry.workingPlan : 'No plan stated.'}</p>
          <h3>Decision</h3>
          <p>{entry.next}</p>
        </>
      )}
    </section>
  );
}
