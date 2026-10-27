import { useEffect, useMemo, useRef, useState } from 'react';
import { answerRecordedText, ApiError, apiRequest, controlAvailability, createRunMonitor, isUncertain, pollDelay, shouldResumeAfterAnswer } from '../console.ts';
import type { Run, Snapshot } from '../console.ts';
import { buildHistory, latestDecision, observationsById } from '../history.ts';
import { currentStepNumber, groupSteps } from '../steps.ts';
import { RunHeader } from './RunHeader.tsx';
import type { ControlOperation, Message } from './RunHeader.tsx';
import { QuestionBlock } from './QuestionBlock.tsx';
import { NowBlock } from './NowBlock.tsx';
import { InterruptedBlock, OutcomeBlock, ReportLinks } from './OutcomeBlock.tsx';
import { StepList } from './StepList.tsx';
import { RunDetails } from './RunDetails.tsx';

interface Props {
  runId: string;
  activeRunId: string | null;
  deleting: boolean;
  onChanged: () => void;
  onBack: () => void;
  onDelete: () => void;
  /** One-click rerun with the same settings; the caller reports a blocked rerun through `rerunBlockedReason`. */
  onRerun: (run: Run) => Promise<void>;
  /** Back to the start screen prefilled with this run's settings. */
  onEditRerun: (run: Run) => void;
  rerunBlockedReason: string | null;
}

/** Where a feedback message belongs: the question block while it is shown, otherwise the header. */
type Feedback = Message & { where: 'header' | 'question' };
type Posted = { ok: true; run: Run } | { ok: false; uncertain: boolean; text: string };

const EMPTY: Snapshot = { run: null, events: [], connected: false, error: null, checkedAt: null };
const CONFIRMED: Record<ControlOperation, string> = {
  pause: 'Pause requested. The current step finishes first; wait for the status to show Paused.',
  resume: 'Resume requested. The AI takes a fresh screenshot before any new action.',
  cancel: 'Cancellation requested. The current step settles first; wait for the status to show Cancelled.',
};
const UNCERTAIN = 'The service did not confirm this request, so it may or may not have been applied. Select Reconnect to check the stored state before trying again.';
const INPUT_NEEDED = 'Input needed · ';

export function RunView({ runId, activeRunId, deleting, onChanged, onBack, onDelete, onRerun, onEditRerun, rerunBlockedReason }: Props) {
  const [snap, setSnap] = useState<Snapshot>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const monitorRef = useRef<ReturnType<typeof createRunMonitor> | null>(null);
  const snapRef = useRef<Snapshot>(EMPTY);
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
    const monitor = createRunMonitor(runId, (value) => { latest = value; snapRef.current = value; setSnap(value); });
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
  const steps = useMemo(() => groupSteps(entries, observations), [entries, observations]);
  const decision = latestDecision(entries);

  const ended = !run || run.state === 'terminal' || run.interrupted;
  const question = !ended && run.pending_question && run.pending_question.cancelled_at === null ? run.pending_question : null;
  const questionOpen = question !== null;

  // Signal an open question in the tab title so it is noticed from another tab.
  useEffect(() => {
    if (!questionOpen) return;
    const previous = document.title;
    document.title = `${INPUT_NEEDED}${previous}`;
    return () => { document.title = previous; };
  }, [questionOpen]);

  async function reconnect() {
    setFeedback(null);
    const ok = await kickRef.current();
    if (ok) setUncertain(false);
    else setFeedback({ tone: 'error', text: 'Still disconnected. Check that the local service is running, then reconnect again.', where: 'header' });
  }

  /** One POST, never retried; an uncertain response blocks every further mutation until Reconnect. */
  async function post(path: string, body?: unknown): Promise<Posted> {
    try {
      const updated = await apiRequest<Run>(`/runs/${encodeURIComponent(runId)}/${path}`, { method: 'POST', body });
      monitorRef.current?.acceptRun(updated);
      return { ok: true, run: updated };
    } catch (error) {
      if (isUncertain(error)) { setUncertain(true); return { ok: false, uncertain: true, text: UNCERTAIN }; }
      return { ok: false, uncertain: false, text: error instanceof ApiError ? error.message : 'The request was not accepted.' };
    }
  }

  async function control(operation: ControlOperation, where: Feedback['where'] = 'header') {
    if (busy || uncertain) return;
    if (operation === 'cancel' && !window.confirm('Cancel this run? The AI will not reach a verdict.')) return;
    setBusy(true);
    setFeedback(null);
    try {
      const result = await post(operation);
      setFeedback(result.ok ? { tone: 'info', text: CONFIRMED[operation], where: 'header' } : { tone: 'error', text: result.text, where });
    } finally {
      setBusy(false);
      void kickRef.current();
    }
  }

  // Answer first; resume only after the answer is confirmed and the run is resumable.
  async function answer(questionId: string, text: string) {
    if (busy || uncertain) return;
    setBusy(true);
    setFeedback(null);
    try {
      const answered = await post('answers', { question_id: questionId, text });
      if (!answered.ok) { setFeedback({ tone: 'error', text: answered.text, where: 'question' }); return; }
      const refreshed = await kickRef.current();
      const latest = refreshed ? snapRef.current.run : null;
      if (!shouldResumeAfterAnswer(answered.run, latest)) {
        setFeedback({ tone: 'info', text: answerRecordedText(latest ?? answered.run), where: 'question' });
        return;
      }
      const resumed = await post('resume');
      if (resumed.ok) setFeedback({ tone: 'info', text: 'Answer recorded and the run resumed. The AI takes a fresh screenshot before any new action.', where: 'header' });
      else setFeedback({ tone: 'error', text: resumed.uncertain ? resumed.text : `Your answer is recorded, but the run did not resume: ${resumed.text}`, where: 'question' });
    } finally {
      setBusy(false);
      void kickRef.current();
    }
  }

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

  const available = controlAvailability(run, snap.connected, busy, uncertain);
  const links = { run, activeRunId, deleting, onDelete };
  const questionFeedback = question && feedback?.where === 'question' ? feedback : null;
  const headerFeedback = feedback && !questionFeedback ? feedback : null;

  return (
    <div className="run-view">
      <RunHeader run={run} step={currentStepNumber(steps)} connected={snap.connected} checkedAt={snap.checkedAt} connectionError={snap.error}
        available={available} busy={busy} uncertain={uncertain} showResume={!question} message={headerFeedback}
        onControl={(operation) => void control(operation)} onReconnect={() => void reconnect()} />

      {question && (
        <QuestionBlock question={question} canAnswer={available.answer} canResume={available.resume} busy={busy} uncertain={uncertain}
          message={questionFeedback} onAnswer={(id, text) => void answer(id, text)} onResume={() => void control('resume', 'question')}
          onReconnect={() => void reconnect()} />
      )}

      {run.interrupted
        ? <InterruptedBlock {...links} onEditRerun={onEditRerun} />
        : run.terminal
        ? <OutcomeBlock {...links} observations={observations} rerunBlockedReason={rerunBlockedReason} onRerun={onRerun} onEditRerun={onEditRerun} />
        : <NowBlock decision={decision} source={decision ? observations.get(decision.sourceObservationId) : undefined} />}

      <StepList steps={steps} observations={observations} ended={ended} />

      <RunDetails run={run}>
        {!run.terminal && !run.interrupted && <ReportLinks {...links} />}
      </RunDetails>
    </div>
  );
}
