import { EFFECT_LABELS, formatDuration, formatTime } from '../history.ts';
import type { ActionMarker, HistoryEntry, ObservationEntry } from '../history.ts';

export function ObservationThumb({ id, entry }: { id: string; entry: ObservationEntry | undefined }) {
  if (!entry || !entry.url) return <span className="thumb missing">Screenshot not found in history</span>;
  return (
    <a className="thumb" href={entry.url} target="_blank" rel="noopener noreferrer" title={id}>
      <img src={entry.url} alt={`Screenshot ${entry.index}, captured ${formatTime(entry.capturedAt)}`} loading="lazy" />
      <span>#{entry.index}</span>
    </a>
  );
}

/** Source screenshot with the touched point or swipe path drawn in its own pixel frame. */
export function ActionShot({ marker, entry, id }: { marker: ActionMarker; entry: ObservationEntry | undefined; id: string }) {
  if (!entry || !entry.url || !(entry.width > 0 && entry.height > 0)) return null;
  const r = Math.max(entry.width, entry.height) * 0.025;
  const arrow = `arrow-${id}`;
  return (
    <a className="action-shot" href={entry.url} target="_blank" rel="noopener noreferrer" title={`On screenshot #${entry.index}`}>
      <img src={entry.url} alt={`Screenshot ${entry.index} with the action location marked`} loading="lazy" width={entry.width} height={entry.height} />
      <svg viewBox={`0 0 ${entry.width} ${entry.height}`} preserveAspectRatio="none" aria-hidden="true">
        {marker.kind === 'point' ? (
          <g className="marker">
            <circle cx={marker.x} cy={marker.y} r={r} className="halo" />
            <circle cx={marker.x} cy={marker.y} r={r} />
            {marker.long && <circle cx={marker.x} cy={marker.y} r={r * 1.8} className="ring" />}
          </g>
        ) : (
          <g className="marker">
            <defs>
              <marker id={arrow} viewBox="0 0 10 10" refX="5" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" className="head" />
              </marker>
            </defs>
            <line x1={marker.x1} y1={marker.y1} x2={marker.x2} y2={marker.y2} className="halo" />
            <line x1={marker.x1} y1={marker.y1} x2={marker.x2} y2={marker.y2} markerEnd={`url(#${arrow})`} />
            <circle cx={marker.x1} cy={marker.y1} r={r * 0.6} className="start" />
          </g>
        )}
      </svg>
    </a>
  );
}

function Entry({ entry, observations }: { entry: HistoryEntry; observations: Map<string, ObservationEntry> }) {
  switch (entry.type) {
    case 'observation':
      return (
        <>
          <span className="entry-kind">Screenshot {entry.index}</span>
          <div className="entry-body observation-row">
            <ObservationThumb id={entry.id} entry={entry} />
            <span className="help">Captured <time dateTime={entry.capturedAt}>{formatTime(entry.capturedAt)}</time></span>
          </div>
        </>
      );
    case 'decision': {
      const shown = entry.presented.map((id) => observations.get(id)?.index).filter((index) => index !== undefined);
      return (
        <>
          <span className="entry-kind">AI decision</span>
          <div className="entry-body">
            {entry.effect && <p className={`effect-line ${entry.effect.verdict}`}><strong>{EFFECT_LABELS[entry.effect.verdict] ?? entry.effect.verdict}:</strong> {entry.effect.explanation}</p>}
            <p className="prewrap">{entry.rationale}</p>
            {entry.planChanged && <details><summary>Working plan updated</summary><p className="prewrap">{entry.workingPlan}</p></details>}
            <p className="decision-next">{entry.next}</p>
            {shown.length > 0 && <p className="help">Looked at screenshot{shown.length > 1 ? 's' : ''} {shown.map((i) => `#${i}`).join(', ')}</p>}
          </div>
        </>
      );
    }
    case 'action':
      return (
        <>
          <span className="entry-kind">Device action</span>
          <div className="entry-body observation-row">
            {entry.marker && <ActionShot marker={entry.marker} entry={observations.get(entry.observationId)} id={entry.id} />}
            <p>{entry.description}</p>
          </div>
        </>
      );
    case 'receipt':
      return (
        <>
          <span className="entry-kind">Technical result</span>
          <div className="entry-body">
            <p className={`receipt ${entry.status}`}>{entry.label}{entry.durationMs !== null ? ` in ${formatDuration(entry.durationMs)}` : ''}</p>
            {entry.detail && <p className="help">{entry.detail}</p>}
            {entry.status === 'completed' && <p className="help">This only means the command was delivered. The AI judges the effect from the next screenshot.</p>}
          </div>
        </>
      );
    case 'question':
      return (<><span className="entry-kind">AI question</span><div className="entry-body"><p>{entry.question}</p></div></>);
    case 'answer':
      return (<><span className="entry-kind">Your answer</span><div className="entry-body"><p>{entry.text}</p><p className="help">Answered <time dateTime={entry.answeredAt}>{formatTime(entry.answeredAt)}</time></p></div></>);
    default:
      return (<><span className="entry-kind">Other record</span><div className="entry-body"><p className="help">Unrecognized record type.</p></div></>);
  }
}

export function EvidenceHistory({ entries, observations }: { entries: HistoryEntry[]; observations: Map<string, ObservationEntry> }) {
  return (
    <section className="panel history" aria-labelledby="history-title">
      <h2 id="history-title">Evidence history</h2>
      <p className="help">Everything recorded for this run, oldest first.</p>
      {entries.length === 0 ? <p className="muted">Nothing recorded yet.</p> : (
        <ol className="timeline">
          {entries.map((entry) => (
            <li key={entry.sequence} className={`entry ${entry.type}`}><Entry entry={entry} observations={observations} /></li>
          ))}
        </ol>
      )}
    </section>
  );
}
