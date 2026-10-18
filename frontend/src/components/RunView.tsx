import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, apiRequest, canDeleteRun, controlAvailability, createRunMonitor, formatTokens, isUncertain, outcome, parseUsage, pollDelay } from '../console.ts';
import type { Run, Snapshot } from '../console.ts';
import { buildHistory, cleanupWarning, formatDuration, formatTime, latestDecision, latestObservation, observationsById, outcomeExplanation } from '../history.ts';
import { RunControls } from './RunControls.tsx';
import type { ControlOperation, Message } from './RunControls.tsx';
import { EvidenceHistory, ObservationThumb } from './EvidenceHistory.tsx';
import { CurrentScreen, LatestThinking } from './CurrentScreen.tsx';
import { parseRunCost, runCostText } from '../stats.ts';

interface Props { runId: string; activeRunId: string | null; deleting: boolean; onChanged: () => void; onBack: () => void; onDelete: () => void; onRerun: (run: Run) => void }

const EMPTY: Snapshot = { run: null, events: [], connected: false, error: null, checkedAt: null };
const CONFIRMED: Record<ControlOperation, string> = {
  pause: 'Pause requested. The current step finishes first; wait for the status to show Paused.',
  resume: 'Resume requested. The AI takes a fresh screenshot before any new action.',
  cancel: 'Cancellation requested. The current step settles first; wait for the status to show Cancelled.',
};
const UNCERTAIN = 'The service did not confirm this request, so it may or may not have been applied. Select Reconnect to check the stored state before trying again.';

export function RunView({ runId, activeRunId, deleting, onChanged, onBack, onDelete, onRerun }: Props) {
  const [snap, setSnap] = useState<Snapshot>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [message, setMessage] = useState<Message | null>(null);
  const monitorRef = useRef<ReturnType<typeof createRunMonitor> | null>(null);
  const kickRef = useRef<() => Promise<boolean>>(async () => false);
  const changedRef = useRef(onChanged);
  useEffect(() => { changedRef.current = onChanged; }, [onChanged]);

  // Read-only polling; mutations are never retried automatically.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    let latest: Snapshot = EMPTY;
    let tick = 0;
    let stopped = false;
    const monitor = createRunMonitor(runId, (value) => { latest = value; setSnap(value); });
    monitorRef.current = monitor;
    const poll = async (): Promise<boolean> => {
      const id = ++tick;
      clearTimeout(timer);
      const ok = await monitor.refresh();
      if (stopped || id !== tick) return ok;
      failures = latest.connected ? 0 : failures + 1;
      const delay = pollDelay(latest, failures);
      if (delay !== null) timer = setTimeout(() => void poll(), delay);
      return ok;
    };
    kickRef.current = poll;
    void poll();
    return () => { stopped = true; clearTimeout(timer); monitor.dispose(); };
  }, [runId]);

  const run = snap.run;
  const stateKey = run ? `${run.state}:${run.interrupted}` : '';
  useEffect(() => { if (stateKey) changedRef.current(); }, [stateKey]);

  const entries = useMemo(() => buildHistory(snap.events, runId), [snap.events, runId]);
  const observations = useMemo(() => observationsById(entries), [entries]);
  const screen = latestObservation(entries);
  const thinking = latestDecision(entries);

  async function reconnect() {
    setMessage(null);
    const ok = await kickRef.current();
    if (ok) setUncertain(false);
    else setMessage({ tone: 'error', text: 'Still disconnected. Check that the local service is running, then reconnect again.' });
  }

  async function mutate(path: string, body: unknown, success: string) {
    if (busy || uncertain) return;
    setBusy(true);
    setMessage(null);
    try {
      const updated = await apiRequest<Run>(`/runs/${encodeURIComponent(runId)}/${path}`, { method: 'POST', body });
      monitorRef.current?.acceptRun(updated);
      setMessage({ tone: 'info', text: success });
      void kickRef.current();
    } catch (error) {
      if (isUncertain(error)) { setUncertain(true); setMessage({ tone: 'error', text: UNCERTAIN }); }
      else setMessage({ tone: 'error', text: error instanceof ApiError ? error.message : 'The request was not accepted.' });
      void kickRef.current();
    } finally {
      setBusy(false);
    }
  }

  const control = (operation: ControlOperation) => {
    if (operation === 'cancel' && !window.confirm('Cancel this run? The AI will not reach a verdict.')) return;
    void mutate(operation, undefined, CONFIRMED[operation]);
  };
  const answer = (questionId: string, text: string) =>
    mutate('answers', { question_id: questionId, text }, 'Answer recorded. Select Resume to let the AI continue.');

  if (!run) {
    return (
      <section className="panel" aria-busy={!snap.error} aria-labelledby="run-loading">
        <h1 id="run-loading">Run</h1>
        <div role="status" aria-live="polite">
          {snap.error ? <p className="error-text">This run could not be loaded. It may not exist, or the local service is unreachable.</p> : <p className="muted">Loading run…</p>}
        </div>
        <div className="actions">
          {snap.error && <button type="button" onClick={() => void reconnect()}>Reconnect</button>}
          <button type="button" className="secondary" onClick={onBack}>New run</button>
        </div>
      </section>
    );
  }

  const badge = outcome(run);
  const available = controlAvailability(run, snap.connected, busy, uncertain);
  const terminal = run.terminal;
  const observeOnly = Array.isArray(run.configuration?.capabilities) && run.configuration.capabilities.length === 0;
  const reportBase = `/api/runs/${encodeURIComponent(run.run_id)}`;
  const usage = parseUsage(run.usage);
  const cost = runCostText(parseRunCost(run.cost));

  return (
    <div className="run-view">
      <section className="panel run-head" aria-labelledby="run-title">
        <div className="run-title-row">
          <h1 id="run-title">{run.goal.text}</h1>
          <div role="status" aria-live="polite" aria-atomic="true" className="run-status">
            <span className={`badge large ${badge.tone}`}>{badge.label}</span>
            {run.control_pending && <span className="badge neutral">{run.control_pending === 'pause' ? 'Pausing…' : run.control_pending === 'cancel' ? 'Cancelling…' : 'Resuming…'}</span>}
          </div>
        </div>
        <p className="outcome-text">{outcomeExplanation(run)}</p>
        {cleanupWarning(run) && <p className="blocked" role="alert">{cleanupWarning(run)}</p>}
        <div className={`connection-line ${snap.connected ? 'ok' : 'lost'}`} role="status" aria-live="polite">
          {snap.connected
            ? <>Updated <time dateTime={snap.checkedAt ? new Date(snap.checkedAt).toISOString() : undefined}>{snap.checkedAt ? new Date(snap.checkedAt).toLocaleTimeString() : ''}</time>{run.state === 'terminal' || run.interrupted ? ' · no further updates expected' : ''}</>
            : snap.error}
          <button type="button" className="link" onClick={() => void reconnect()}>{snap.connected ? 'Refresh' : 'Reconnect'}</button>
        </div>
        <dl className="facts compact">
          <div><dt>Device</dt><dd>{run.device_id}</dd></div>
          <div><dt>Mode</dt><dd>{observeOnly ? 'Observe only' : 'AI may operate the device'}</dd></div>
          <div><dt>Started</dt><dd><time dateTime={run.created_at}>{formatTime(run.created_at)}</time></dd></div>
          <div><dt>AI model</dt><dd>{run.configuration?.identity?.model ?? 'unknown'}</dd></div>
          <div><dt>Input tokens</dt><dd>{usage ? formatTokens(usage.input_tokens) : 'unknown'}</dd></div>
          <div><dt>Output tokens</dt><dd>{usage ? formatTokens(usage.output_tokens) : 'unknown'}</dd></div>
          <div><dt>Estimated cost</dt><dd title={cost.title}>{cost.text}</dd></div>
          <div><dt>Limits</dt><dd>{formatDuration(run.configuration.limits.wall_time_ms)}, {run.configuration.limits.max_actions} actions, {run.configuration.limits.max_inferences} AI steps</dd></div>
        </dl>
        {(run.goal.expected_result || run.goal.constraints.length > 0) && (
          <div className="goal-extra">
            {run.goal.expected_result && <p><strong>Expected result:</strong> {run.goal.expected_result}</p>}
            {run.goal.constraints.length > 0 && <><strong>Constraints:</strong><ul>{run.goal.constraints.map((item, i) => <li key={i}>{item}</li>)}</ul></>}
          </div>
        )}
        <div className="report-links">
          <a href={`${reportBase}/report.html`} target="_blank" rel="noopener noreferrer">Open readable report</a>
          <a href={`${reportBase}/report.json`} download>Download report data (JSON)</a>
          <button type="button" className="link" onClick={() => onRerun(run)}
            title="Open a new run form prefilled with this goal, expected result, constraints, model, mode and limits">Run again with these settings</button>
          {canDeleteRun(run, activeRunId) && (
            <button type="button" className="link danger-link" disabled={deleting} onClick={onDelete}>{deleting ? 'Deleting…' : 'Delete this run'}</button>
          )}
        </div>
        {usage && usage.unknown_usage_decisions > 0 && (
          <p className="help">{usage.unknown_usage_decisions} AI steps did not report token usage and are not counted.</p>
        )}
      </section>

      {terminal && (
        <section className={`panel verdict ${badge.tone}`} aria-labelledby="verdict-title">
          <h2 id="verdict-title">{terminal.kind === 'ai_conclusion' ? 'AI verdict' : 'How the run ended'}</h2>
          {terminal.kind === 'ai_conclusion' && (
            <>
              <p className="verdict-text">{terminal.assessment.explanation}</p>
              <p className="help">Screenshots the AI referenced:</p>
              <div className="thumbs">
                {terminal.assessment.observation_ids.map((id) => <ObservationThumb key={id} id={id} entry={observations.get(id)} />)}
              </div>
            </>
          )}
          {terminal.kind === 'infrastructure_failure' && (
            <>
              <p>{terminal.detail}</p>
              <details><summary>Technical details</summary><p>Component: {terminal.component}</p></details>
            </>
          )}
          {terminal.kind === 'cancelled' && <p>Cancelled by: {terminal.source}</p>}
          {terminal.kind === 'budget_exhausted' && terminal.usage && (
            <p>Used {formatDuration(terminal.usage.elapsed_ms)}, {terminal.usage.actions} device actions and {terminal.usage.inferences} AI steps.</p>
          )}
          <p className="help">Recorded <time dateTime={terminal.recorded_at}>{formatTime(terminal.recorded_at)}</time></p>
        </section>
      )}

      <RunControls run={run} available={available} busy={busy} uncertain={uncertain} message={message}
        onControl={control} onAnswer={answer} onReconnect={() => void reconnect()} />

      <div className="live-grid">
        <CurrentScreen run={run} connected={snap.connected} entry={screen} />
        <LatestThinking entry={thinking} />
      </div>

      <EvidenceHistory entries={entries} observations={observations} />
    </div>
  );
}
