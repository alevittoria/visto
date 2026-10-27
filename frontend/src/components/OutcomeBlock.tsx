import { useState } from 'react';
import { canDeleteRun, outcome } from '../console.ts';
import type { Run, TerminalRecord } from '../console.ts';
import { formatDuration, formatTime, outcomeExplanation } from '../history.ts';
import type { ObservationEntry } from '../history.ts';
import { ObservationThumb } from './EvidenceHistory.tsx';

interface LinkProps { run: Run; activeRunId: string | null; deleting: boolean; onDelete: () => void }

/** Minor links: stored reports and deletion (the deletion itself asks for confirmation). */
export function ReportLinks({ run, activeRunId, deleting, onDelete }: LinkProps) {
  const base = `/api/runs/${encodeURIComponent(run.run_id)}`;
  return (
    <div className="report-links">
      <a href={`${base}/report.html`} target="_blank" rel="noopener noreferrer">Open readable report</a>
      <a href={`${base}/report.json`} download>Download report data (JSON)</a>
      {canDeleteRun(run, activeRunId) && (
        <button type="button" className="link danger-link" disabled={deleting} onClick={onDelete}>{deleting ? 'Deleting…' : 'Delete this run'}</button>
      )}
    </div>
  );
}

function heading(terminal: TerminalRecord): { kicker: string; title: string; icon: string } {
  switch (terminal.kind) {
    case 'ai_conclusion': {
      const verdict = terminal.assessment?.verdict;
      if (verdict === 'passed') return { kicker: 'AI verdict', title: 'Passed', icon: '✔' };
      if (verdict === 'failed') return { kicker: 'AI verdict', title: 'Failed', icon: '✖' };
      return { kicker: 'AI verdict', title: 'Inconclusive', icon: '?' };
    }
    case 'infrastructure_failure': return { kicker: 'No verdict', title: 'Technical failure', icon: '!' };
    case 'cancelled': return { kicker: 'No verdict', title: 'Cancelled', icon: '■' };
    case 'budget_exhausted': return { kicker: 'No verdict', title: 'Limit reached', icon: '⧗' };
    default: return { kicker: 'Run ended', title: 'Ended', icon: '•' };
  }
}

interface Props extends LinkProps {
  observations: Map<string, ObservationEntry>;
  rerunBlockedReason: string | null;
  onRerun: (run: Run) => Promise<void>;
  onEditRerun: (run: Run) => void;
}

/** Final outcome of an ended run, colored by its kind, with the ways to run it again. */
export function OutcomeBlock({ run, observations, rerunBlockedReason, onRerun, onEditRerun, ...links }: Props) {
  const [rerunning, setRerunning] = useState(false);
  const terminal = run.terminal;
  if (!terminal) return null;
  const { kicker, title, icon } = heading(terminal);
  const tone = outcome(run).tone;
  const referenced = terminal.kind === 'ai_conclusion' ? terminal.assessment.observation_ids
    : terminal.kind === 'infrastructure_failure' ? terminal.observation_ids ?? [] : [];

  async function rerun() {
    if (rerunning) return;
    setRerunning(true);
    try { await onRerun(run); } finally { setRerunning(false); }
  }

  return (
    <section className={`panel outcome-block ${tone}`} aria-labelledby="outcome-title" aria-live="polite">
      <div className="outcome-head">
        <span className="outcome-icon" aria-hidden="true">{icon}</span>
        <div>
          <p className="kicker">{kicker}</p>
          <h2 id="outcome-title" className="outcome-title">{title}</h2>
        </div>
      </div>
      {terminal.kind === 'ai_conclusion' && (
        <>
          <p className="outcome-explanation">{terminal.assessment.explanation}</p>
          <p className="help">{outcomeExplanation(run)}</p>
        </>
      )}
      {terminal.kind === 'infrastructure_failure' && (
        <>
          <p className="outcome-explanation">{terminal.detail}</p>
          <p className="help">{outcomeExplanation(run)}</p>
          <details><summary>Technical details</summary><p>Component: {terminal.component}</p></details>
        </>
      )}
      {terminal.kind === 'cancelled' && (
        <>
          <p className="outcome-explanation">{outcomeExplanation(run)}</p>
          <p className="help">Cancelled by: {terminal.source}</p>
        </>
      )}
      {terminal.kind === 'budget_exhausted' && (
        <>
          <p className="outcome-explanation">{outcomeExplanation(run)}</p>
          {terminal.usage && <p className="help">Used {formatDuration(terminal.usage.elapsed_ms)}, {terminal.usage.actions} device actions and {terminal.usage.inferences} AI steps.</p>}
        </>
      )}
      {referenced.length > 0 && (
        <>
          <p className="help">{terminal.kind === 'ai_conclusion' ? 'Screenshots the AI referenced:' : 'Screenshots recorded with the failure:'}</p>
          <div className="thumbs">
            {referenced.map((id) => <ObservationThumb key={id} id={id} entry={observations.get(id)} />)}
          </div>
        </>
      )}
      <p className="help">Recorded <time dateTime={terminal.recorded_at}>{formatTime(terminal.recorded_at)}</time></p>
      <div className="outcome-actions">
        <button type="button" onClick={() => void rerun()} disabled={rerunning} aria-busy={rerunning}
          title="Start a new run now with the same goal, expected result, constraints, model, mode, limits and device">
          {rerunning && <span className="spinner" aria-hidden="true" />}{rerunning ? 'Starting…' : 'Rerun'}
        </button>
        <button type="button" className="secondary" onClick={() => onEditRerun(run)}
          title="Open the start screen prefilled with these settings">Edit and rerun</button>
        <p className="rerun-blocked" role="status" aria-live="polite">{rerunBlockedReason}</p>
      </div>
      <ReportLinks run={run} {...links} />
    </section>
  );
}

/** A run this console does not control: no verdict here, only its evidence and a prefilled new run. */
export function InterruptedBlock({ run, onEditRerun, ...links }: LinkProps & { onEditRerun: (run: Run) => void }) {
  return (
    <section className="panel interrupted-block" aria-labelledby="interrupted-title">
      <h2 id="interrupted-title">Not controlled by this console</h2>
      <p>{outcomeExplanation(run)}</p>
      <p className="help">No verdict is available here.</p>
      <div className="outcome-actions">
        <button type="button" onClick={() => onEditRerun(run)} title="Open the start screen prefilled with these settings">Edit and rerun</button>
      </div>
      <ReportLinks run={run} {...links} />
    </section>
  );
}
