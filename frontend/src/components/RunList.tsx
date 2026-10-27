import { canDeleteRun, outcome } from '../console.ts';
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
  /** Present when the history is shown as an overlay drawer. */
  onClose?: () => void;
}

/** Run history sidebar: a new-run action on top, then stored runs, newest first. */
export function RunList({ state, selected, activeRunId, deleting, deleteError, onSelect, onNew, onRefresh, onDelete, onDeleteAll, onClose }: Props) {
  const deletable = state.runs.some((run) => canDeleteRun(run, activeRunId));
  return (
    <nav className="run-list" aria-labelledby="runs-title">
      <div className="run-list-top">
        <button type="button" className="secondary new-run" onClick={onNew}>
          <span aria-hidden="true">+</span> New run
        </button>
        {onClose && (
          <button type="button" className="secondary icon-button" onClick={onClose} aria-label="Close run history">
            <span aria-hidden="true">×</span>
          </button>
        )}
      </div>
      <h2 id="runs-title" className="run-list-title">History</h2>
      {state.error && <p className="error-text small-text" role="status">{state.error} <button type="button" className="link" onClick={onRefresh}>Retry</button></p>}
      {deleteError && <p className="error-text small-text" role="alert">{deleteError}</p>}
      {!state.error && state.runs.length === 0 && <p className="muted small-text">{state.loading ? 'Loading…' : 'No runs yet.'}</p>}
      <ul>
        {state.runs.map((run) => {
          const badge = outcome(run);
          return (
            <li key={run.run_id} className="run-row">
              <button type="button" className={`run-item${run.run_id === selected ? ' selected' : ''}`}
                aria-current={run.run_id === selected ? 'page' : undefined} onClick={() => onSelect(run.run_id)}>
                <span className="run-item-goal">{run.goal?.text ?? 'Untitled run'}</span>
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
        <button type="button" className="secondary small danger delete-all" disabled={deleting} onClick={onDeleteAll}>
          {deleting ? 'Deleting…' : 'Delete all runs'}
        </button>
      )}
    </nav>
  );
}
