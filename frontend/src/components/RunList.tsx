import { canDeleteRun, formatTokens, outcome } from '../console.ts';
import { formatTime } from '../history.ts';
import type { RunsState } from '../App.tsx';

interface Props {
  state: RunsState;
  selected: string | null;
  activeRunId: string | null;
  deleting: boolean;
  deleteError: string | null;
  onSelect: (runId: string) => void;
  onNew: () => void;
  onRefresh: () => void;
  onDelete: (runId: string) => void;
  onDeleteAll: () => void;
}

export function RunList({ state, selected, activeRunId, deleting, deleteError, onSelect, onNew, onRefresh, onDelete, onDeleteAll }: Props) {
  const deletable = state.runs.some((run) => canDeleteRun(run, activeRunId));
  return (
    <nav className="run-list" aria-labelledby="runs-title">
      <div className="run-list-head">
        <h2 id="runs-title">Runs</h2>
        <button type="button" className="secondary small" onClick={onNew} aria-pressed={selected === null}>New run</button>
      </div>
      {state.usage && (
        <dl className="token-summary" aria-label="AI tokens used by all stored runs">
          <div><dt>Input tokens</dt><dd>{formatTokens(state.usage.input_tokens)}</dd></div>
          <div><dt>Output tokens</dt><dd>{formatTokens(state.usage.output_tokens)}</dd></div>
          {state.usage.unknown_usage_decisions > 0 && (
            <p className="help">{state.usage.unknown_usage_decisions} AI steps did not report usage and are not counted.</p>
          )}
        </dl>
      )}
      {state.error && <p className="error-text small-text" role="status">{state.error} <button type="button" className="link" onClick={onRefresh}>Retry</button></p>}
      {deleteError && <p className="error-text small-text" role="alert">{deleteError}</p>}
      {!state.error && state.runs.length === 0 && <p className="muted small-text">{state.loading ? 'Loading…' : 'No runs yet.'}</p>}
      <ul>
        {state.runs.map((run) => {
          const badge = outcome(run);
          return (
            <li key={run.run_id} className="run-row">
              <button type="button" className={`run-item${run.run_id === selected ? ' selected' : ''}`}
                aria-current={run.run_id === selected ? 'true' : undefined} onClick={() => onSelect(run.run_id)}>
                <span className="run-goal">{run.goal?.text ?? 'Untitled run'}</span>
                <span className="run-meta">
                  <span className={`badge ${badge.tone}`}>{badge.label}</span>
                  {run.cleanup_failed && <span className="badge warning">Check device</span>}
                  <time dateTime={run.created_at}>{formatTime(run.created_at)}</time>
                </span>
              </button>
              {canDeleteRun(run, activeRunId) && (
                <button type="button" className="link danger-link" disabled={deleting}
                  aria-label={`Delete run: ${run.goal?.text ?? run.run_id}`} title="Delete run" onClick={() => onDelete(run.run_id)}>Delete</button>
              )}
            </li>
          );
        })}
      </ul>
      {deletable && (
        <button type="button" className="secondary small danger" disabled={deleting} onClick={onDeleteAll}>
          {deleting ? 'Deleting…' : 'Delete all runs'}
        </button>
      )}
    </nav>
  );
}
