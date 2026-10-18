// Pure projection of stored run events into readable evidence entries.
// Nothing here infers a test verdict: only the AI's terminal assessment does.
import { safeScreenshotUrl } from './console.ts';
import type {
  Action, Decision, DeviceCommand, EffectAssessment, NextDecision, Observation, PendingQuestion,
  ReceiptStatus, Run, RunEvent, TechnicalReceipt, UserAnswer,
} from './console.ts';

export interface ObservationEntry { type: 'observation'; sequence: number; id: string; capturedAt: string; url: string | null; width: number; height: number; index: number }
export interface DecisionEntry {
  type: 'decision'; sequence: number; id: string; rationale: string; workingPlan: string; planChanged: boolean;
  next: string; nextKind: NextDecision['kind']; effect: EffectAssessment | null; presented: string[]; sourceObservationId: string;
}
/** Where a pointer command touched the source screenshot, in its pixel frame. */
export type ActionMarker =
  | { kind: 'point'; x: number; y: number; long: boolean }
  | { kind: 'line'; x1: number; y1: number; x2: number; y2: number };
export interface ActionEntry { type: 'action'; sequence: number; id: string; description: string; observationId: string; timeoutMs: number; marker: ActionMarker | null }
export interface ReceiptEntry { type: 'receipt'; sequence: number; actionId: string; status: ReceiptStatus; label: string; detail: string; durationMs: number | null; finishedAt: string }
export interface QuestionEntry { type: 'question'; sequence: number; id: string; question: string; createdAt: string }
export interface AnswerEntry { type: 'answer'; sequence: number; questionId: string; text: string; answeredBy: string; answeredAt: string }
export interface UnknownEntry { type: 'unknown'; sequence: number; kind: string }
export type HistoryEntry = ObservationEntry | DecisionEntry | ActionEntry | ReceiptEntry | QuestionEntry | AnswerEntry | UnknownEntry;

export function describeCommand(command: DeviceCommand | undefined): string {
  switch (command?.kind) {
    case 'tap': return `Tap at (${command.x}, ${command.y})`;
    case 'long_press': return `Long press at (${command.x}, ${command.y}) for ${formatDuration(command.duration_ms)}`;
    case 'swipe': return `Swipe from (${command.start_x}, ${command.start_y}) to (${command.end_x}, ${command.end_y}) over ${formatDuration(command.duration_ms)}`;
    case 'type_text': return `Type “${command.text}”`;
    case 'back': return 'Press Back';
    case 'home': return 'Go to the Home screen';
    case 'enter': return 'Press Enter';
    default: return 'Unrecognized device action';
  }
}

const finite = (...values: unknown[]) => values.every((v) => typeof v === 'number' && Number.isFinite(v));

/** Overlay geometry for pointer commands; key and text commands have none. */
export function actionMarker(command: DeviceCommand | undefined): ActionMarker | null {
  switch (command?.kind) {
    case 'tap':
    case 'long_press':
      return finite(command.x, command.y) ? { kind: 'point', x: command.x, y: command.y, long: command.kind === 'long_press' } : null;
    case 'swipe':
      return finite(command.start_x, command.start_y, command.end_x, command.end_y)
        ? { kind: 'line', x1: command.start_x, y1: command.start_y, x2: command.end_x, y2: command.end_y } : null;
    default: return null;
  }
}

export function describeNext(next: NextDecision | undefined): string {
  switch (next?.kind) {
    case 'act': return `Next: ${describeCommand(next.command)}`;
    case 'observe_after': return `Next: wait ${formatDuration(next.delay_ms)} and look again`;
    case 'ask_user': return `Next: ask you “${next.question}”`;
    case 'conclude': return `Concluded: AI ${next.assessment?.verdict ?? 'unknown'}`;
    default: return 'Next step not recognized';
  }
}

// Receipt labels describe command transport only, never test success.
export const RECEIPT_LABELS: Record<ReceiptStatus, string> = {
  completed: 'Device command completed (technical only)',
  rejected: 'Device command rejected',
  error: 'Device command failed',
  uncertain: 'Device command outcome unknown',
};

export const EFFECT_LABELS: Record<string, string> = {
  achieved: 'AI saw the intended effect',
  not_achieved: 'AI did not see the intended effect',
  unclear: 'AI could not tell the effect',
};

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms)) return 'unknown time';
  if (ms < 1000) return `${ms} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${Number.isInteger(seconds) ? seconds : seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
}

function elapsed(from: string | null | undefined, to: string | null | undefined): number | null {
  if (!from || !to) return null;
  const value = Date.parse(to) - Date.parse(from);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

/** Maps raw events in sequence order to typed history entries. */
export function buildHistory(events: RunEvent[], runId: string): HistoryEntry[] {
  const entries: HistoryEntry[] = [];
  let previousPlan: string | null = null;
  let observationIndex = 0;
  for (const event of [...events].sort((a, b) => a.sequence - b.sequence)) {
    const sequence = event.sequence;
    switch (event.kind) {
      case 'observation': {
        const data = event.data as unknown as Observation;
        observationIndex += 1;
        entries.push({ type: 'observation', sequence, id: data.observation_id, capturedAt: data.captured_at,
          url: safeScreenshotUrl(data.screenshot?.url, runId), width: data.width, height: data.height, index: observationIndex });
        break;
      }
      case 'agent_decision': {
        const data = event.data as unknown as Decision;
        const plan = typeof data.working_plan === 'string' ? data.working_plan : '';
        const planChanged = plan.trim() !== '' && (previousPlan === null || plan.trim() !== previousPlan.trim());
        if (plan.trim()) previousPlan = plan;
        entries.push({ type: 'decision', sequence, id: data.decision_id, rationale: data.rationale ?? '', workingPlan: plan, planChanged,
          next: describeNext(data.next), nextKind: data.next?.kind, effect: data.previous_effect ?? null,
          presented: Array.isArray(data.presented_observation_ids) ? data.presented_observation_ids : [],
          sourceObservationId: data.source_observation_id });
        break;
      }
      case 'action': {
        const data = event.data as unknown as Action;
        entries.push({ type: 'action', sequence, id: data.action_id, description: describeCommand(data.command),
          observationId: data.observation_id, timeoutMs: data.timeout_ms, marker: actionMarker(data.command) });
        break;
      }
      case 'technical_receipt': {
        const data = event.data as unknown as TechnicalReceipt;
        entries.push({ type: 'receipt', sequence, actionId: data.action_id, status: data.status,
          label: RECEIPT_LABELS[data.status] ?? 'Device command status unknown', detail: data.detail ?? '',
          durationMs: elapsed(data.dispatched_at, data.finished_at), finishedAt: data.finished_at });
        break;
      }
      case 'pending_question': {
        const data = event.data as unknown as PendingQuestion;
        entries.push({ type: 'question', sequence, id: data.question_id, question: data.question, createdAt: data.created_at });
        break;
      }
      case 'user_answer': {
        const data = event.data as unknown as UserAnswer;
        entries.push({ type: 'answer', sequence, questionId: data.question_id, text: data.text, answeredBy: data.answered_by, answeredAt: data.answered_at });
        break;
      }
      default:
        entries.push({ type: 'unknown', sequence, kind: event.kind });
    }
  }
  return entries;
}

export function latestObservation(entries: HistoryEntry[]): ObservationEntry | null {
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    const entry = entries[i];
    if (entry.type === 'observation') return entry;
  }
  return null;
}

export function latestDecision(entries: HistoryEntry[]): DecisionEntry | null {
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    const entry = entries[i];
    if (entry.type === 'decision') return entry;
  }
  return null;
}

export function observationsById(entries: HistoryEntry[]): Map<string, ObservationEntry> {
  const map = new Map<string, ObservationEntry>();
  for (const entry of entries) if (entry.type === 'observation') map.set(entry.id, entry);
  return map;
}

/** Whether the shown screenshot may be treated as current; it is never a live view. */
export function screenshotFreshness(run: Run | null, connected: boolean): { current: boolean; label: string } {
  if (!connected) return { current: false, label: 'Stale: updates disconnected' };
  if (!run) return { current: false, label: 'Loading' };
  if (run.interrupted) return { current: false, label: 'Stale: run is not executing in this console' };
  if (run.state === 'running' || run.state === 'created') return { current: true, label: 'Latest capture (not a live view)' };
  if (run.state === 'terminal') return { current: false, label: 'Final capture: run has ended' };
  return { current: false, label: 'Stale: run is suspended' };
}

const BUDGETS: Record<string, string> = { wall_time: 'total time limit', actions: 'device action limit', inferences: 'AI step limit' };

/** Plain-language explanation of what kind of outcome the run has. */
export function outcomeExplanation(run: Run): string {
  if (run.interrupted) return 'This run is not executing in this console. It may still be running from a terminal (CLI), or it was interrupted when the service restarted. Its stored evidence is shown; use Refresh to check for newer records. It cannot be controlled here. Check the device before starting a new run on it.';
  const terminal = run.terminal;
  if (!terminal) {
    if (run.state === 'waiting_for_user') return 'The AI asked a question and is waiting for your answer.';
    if (run.state === 'paused') return 'Paused. No new device actions are sent until you resume.';
    return 'The AI is observing the device and choosing actions. No verdict yet.';
  }
  switch (terminal.kind) {
    case 'ai_conclusion': return `The AI concluded the test ${terminal.assessment.verdict === 'inconclusive' ? 'is inconclusive' : terminal.assessment.verdict}. This is the AI's judgement based on the screenshots it referenced.`;
    case 'infrastructure_failure': return 'The run stopped because of a technical problem (device, AI service or storage). This is not a test verdict.';
    case 'cancelled': return 'The run was cancelled before the AI reached a conclusion. This is not a test verdict.';
    case 'budget_exhausted': return `The run reached its ${BUDGETS[terminal.budget] ?? 'limit'} before the AI concluded. This is not a test verdict.`;
    default: return 'The run ended.';
  }
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return 'unknown time';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? 'unknown time' : date.toLocaleString();
}

/** Separate device-cleanup warning; the stored outcome above stays authoritative. */
export function cleanupWarning(run: Run): string | null {
  if (run.cleanup_failed !== true) return null;
  return `Device cleanup did not finish after this run ended. The result above is unchanged, but check device ${run.device_id} and its automation session before starting another run on it.`;
}
