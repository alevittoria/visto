import { useLayoutEffect, useRef, useState } from 'react';
import { outcome } from '../console.ts';
import type { ControlAvailability, Run } from '../console.ts';
import { cleanupWarning } from '../history.ts';

export type ControlOperation = 'pause' | 'resume' | 'cancel';
export interface Message { tone: 'info' | 'error'; text: string }

/** Header badge: live state with the step count while running, the stored outcome once ended. */
export function stateBadge(run: Run, step: number): { label: string; tone: string } {
  if (run.interrupted || run.state === 'terminal') return outcome(run);
  switch (run.state) {
    case 'running': return { label: step > 0 ? `Running · step ${step}` : 'Running', tone: 'active' };
    case 'paused': return { label: 'Paused', tone: 'neutral' };
    case 'waiting_for_user': return run.pending_question?.answer
      ? { label: 'Answer recorded · resume to continue', tone: 'attention' }
      : { label: 'Waiting for your answer', tone: 'attention' };
    default: return { label: 'Starting', tone: 'active' };
  }
}

const PENDING: Record<ControlOperation, string> = { pause: 'Pausing…', resume: 'Resuming…', cancel: 'Cancelling…' };

interface Props {
  run: Run;
  step: number;
  connected: boolean;
  checkedAt: number | null;
  connectionError: string | null;
  available: ControlAvailability;
  busy: boolean;
  uncertain: boolean;
  /** Resume lives in the question block while a question is open. */
  showResume: boolean;
  message: Message | null;
  onControl: (operation: ControlOperation) => void;
  onReconnect: () => void;
}

export function RunHeader({ run, step, connected, checkedAt, connectionError, available, busy, uncertain, showResume, message, onControl, onReconnect }: Props) {
  const goalRef = useRef<HTMLHeadingElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [clamped, setClamped] = useState(false);
  const ended = run.state === 'terminal' || run.interrupted;
  const badge = stateBadge(run, step);
  const warning = cleanupWarning(run);

  // Offer "Show more" only when the two-line clamp actually hides text.
  useLayoutEffect(() => {
    const element = goalRef.current;
    if (!element || expanded) return;
    const measure = () => setClamped(element.scrollHeight > element.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [run.goal.text, expanded]);

  return (
    <section className="panel run-head" aria-labelledby="run-title">
      <div className="run-head-bar">
        <div role="status" aria-live="polite" aria-atomic="true" className="run-status">
          <span className={`badge large ${badge.tone}`}>{badge.label}</span>
          {run.control_pending && <span className="badge neutral">{PENDING[run.control_pending]}</span>}
        </div>
        {!ended && (
          <div className="run-controls">
            {(run.state === 'created' || run.state === 'running') && (
              <button type="button" className="secondary small" onClick={() => onControl('pause')} disabled={!available.pause}
                title="Takes effect after the current step settles">Pause</button>
            )}
            {showResume && run.state !== 'created' && run.state !== 'running' && (
              <button type="button" className="small" onClick={() => onControl('resume')} disabled={!available.resume}
                title="The AI takes a fresh screenshot before any new action">Resume</button>
            )}
            <button type="button" className="danger small" onClick={() => onControl('cancel')} disabled={!available.cancel}
              title="Takes effect after the current step settles">Cancel run</button>
          </div>
        )}
      </div>
      <h1 id="run-title" ref={goalRef} className={`run-goal${expanded ? '' : ' clamped'}`}>{run.goal.text}</h1>
      {(clamped || expanded) && (
        <button type="button" className="link goal-toggle" aria-expanded={expanded} aria-controls="run-title" onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
      {warning && <p className="blocked" role="alert">{warning}</p>}
      <div className={`connection-line ${connected ? 'ok' : 'lost'}`} role="status" aria-live="polite">
        {connected
          ? <span>Updated <time dateTime={checkedAt ? new Date(checkedAt).toISOString() : undefined}>{checkedAt ? new Date(checkedAt).toLocaleTimeString() : ''}</time>{ended ? ' · no further updates expected' : ''}</span>
          : <span>{connectionError}</span>}
        <button type="button" className={connected ? 'link' : 'secondary small'} onClick={onReconnect}>{connected ? 'Refresh' : 'Reconnect'}</button>
      </div>
      <div aria-live="polite" aria-atomic="true" className="run-feedback">
        {message && <p className={message.tone === 'error' ? 'error-text' : 'info-text'}>{message.text}</p>}
        {uncertain && message && <button type="button" className="secondary small" onClick={onReconnect}>Reconnect</button>}
        {busy && !message && <p className="muted">Sending…</p>}
      </div>
    </section>
  );
}
