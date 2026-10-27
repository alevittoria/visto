// Typed client for the local execution API (docs/api-contract.md).
// Shapes mirror backend `public()` serialization: nested dataclasses carry a
// snake_case `kind`, enums are string values and timestamps are ISO 8601.

export interface Limits {
  wall_time_ms: number;
  max_actions: number;
  max_inferences: number;
  max_command_timeout_ms: number;
  max_observation_delay_ms: number;
}

export const DEFAULT_LIMITS: Limits = {
  wall_time_ms: 1200000, max_actions: 60, max_inferences: 90,
  max_command_timeout_ms: 60000, max_observation_delay_ms: 10000,
};

export interface Readiness {
  configured: boolean;
  provider_key_configured: boolean;
  configuration_error: string | null;
  model: string | null;
  /** Operator-selectable AI models; the server rejects anything else. */
  models: string[];
  appium_url: string | null;
  device_selection: 'manual';
  devices: string[];
  /** Platforms this server lists devices for; iOS only on a Mac. */
  platforms: Platform[];
  active_run_id: string | null;
  execution_available: boolean;
  default_limits: Limits;
  /** Runs whose device/lease cleanup failed after they ended; operator must check the device. */
  cleanup_attention_run_ids: string[];
}

export type SemanticVerdict = 'passed' | 'failed' | 'inconclusive';
export type EffectVerdict = 'achieved' | 'not_achieved' | 'unclear';
export type ReceiptStatus = 'completed' | 'rejected' | 'error' | 'uncertain';
export type RunState = 'created' | 'running' | 'paused' | 'waiting_for_user' | 'terminal';

export interface Assessment {
  kind?: 'assessment';
  run_id?: string;
  decision_id?: string;
  verdict: SemanticVerdict;
  explanation: string;
  observation_ids: string[];
}

export interface EffectAssessment {
  kind?: 'effect_assessment';
  action_id: string;
  verdict: EffectVerdict;
  explanation: string;
  observation_ids: string[];
}

export type DeviceCommand =
  | { kind: 'tap'; x: number; y: number }
  | { kind: 'long_press'; x: number; y: number; duration_ms: number }
  | { kind: 'swipe'; start_x: number; start_y: number; end_x: number; end_y: number; duration_ms: number }
  | { kind: 'type_text'; text: string }
  | { kind: 'back' }
  | { kind: 'home' }
  | { kind: 'enter' };

export type NextDecision =
  | { kind: 'act'; command: DeviceCommand; timeout_ms: number }
  | { kind: 'observe_after'; delay_ms: number }
  | { kind: 'ask_user'; question: string }
  | { kind: 'conclude'; assessment: Assessment };

export interface UserAnswer {
  kind?: 'user_answer';
  question_id: string;
  run_id: string;
  text: string;
  answered_by: string;
  answered_at: string;
}

export interface PendingQuestion {
  kind?: 'pending_question';
  question_id: string;
  run_id: string;
  decision_id: string;
  question: string;
  created_at: string;
  answer: UserAnswer | null;
  cancelled_at: string | null;
}

export type TerminalRecord =
  | { kind: 'ai_conclusion'; run_id: string; recorded_at: string; assessment: Assessment }
  | { kind: 'infrastructure_failure'; run_id: string; recorded_at: string; component: string; detail: string; observation_ids: string[] }
  | { kind: 'cancelled'; run_id: string; recorded_at: string; source: string }
  | { kind: 'budget_exhausted'; run_id: string; recorded_at: string; budget: 'wall_time' | 'actions' | 'inferences';
      usage: { elapsed_ms: number; actions: number; inferences: number } };

export interface Run {
  run_id: string;
  device_id: string;
  goal: { text: string; expected_result: string | null; constraints: string[] };
  configuration: { limits: Limits; capabilities: string[]; identity: { provider: string; model: string; instruction_version: string };
    device_adapter_version: string };
  created_at: string;
  updated_at: string;
  revision: number;
  state: RunState;
  can_resume: boolean;
  interrupted: boolean;
  control_pending: 'pause' | 'resume' | 'cancel' | null;
  /** Device/lease cleanup failed after the run ended; never changes the stored outcome. */
  cleanup_failed?: boolean;
  pending_question: PendingQuestion | null;
  terminal: TerminalRecord | null;
  usage?: TokenUsage;
  /** Only on GET /runs/{id}; see stats.ts parseRunCost. */
  cost?: unknown;
}

/** Tokens from persisted AI decisions only; failed or unrecorded requests are not counted. */
export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  recorded_decisions: number;
  unknown_usage_decisions: number;
}

export function parseUsage(value: unknown): TokenUsage | null {
  const v = value as Partial<TokenUsage> | null;
  if (typeof v !== 'object' || v === null) return null;
  const keys = ['input_tokens', 'output_tokens', 'recorded_decisions', 'unknown_usage_decisions'] as const;
  if (keys.some((key) => !Number.isSafeInteger(v[key]) || (v[key] as number) < 0)) return null;
  return { input_tokens: v.input_tokens!, output_tokens: v.output_tokens!,
    recorded_decisions: v.recorded_decisions!, unknown_usage_decisions: v.unknown_usage_decisions! };
}

export function formatTokens(value: number): string {
  return value.toLocaleString('en-US');
}

export interface Observation {
  kind?: 'observation';
  observation_id: string;
  run_id: string;
  sequence: number;
  captured_at: string;
  device_id: string;
  width: number;
  height: number;
  rotation: number;
  screenshot: { artifact_id: string; run_id: string; media_type: string; byte_length: number; sha256: string; url: string };
}

export interface Decision {
  kind?: 'agent_decision';
  decision_id: string;
  run_id: string;
  rationale: string;
  working_plan: string;
  presented_observation_ids: string[];
  source_observation_id: string;
  previous_effect: EffectAssessment | null;
  next: NextDecision;
  identity: { provider: string; model: string; instruction_version: string };
  usage: { input_tokens: number | null; output_tokens: number | null };
}

export interface Action {
  kind?: 'action';
  action_id: string;
  run_id: string;
  decision_id: string;
  observation_id: string;
  command: DeviceCommand;
  timeout_ms: number;
}

export interface TechnicalReceipt {
  kind?: 'technical_receipt';
  run_id: string;
  action_id: string;
  status: ReceiptStatus;
  dispatched_at: string;
  started_at: string | null;
  finished_at: string;
  detail: string;
}

export interface RunEvent {
  sequence: number;
  kind: string;
  data: Record<string, unknown>;
}

export interface RunPage { runs: Run[]; limit: number; offset: number }
export interface Snapshot { run: Run | null; events: RunEvent[]; connected: boolean; error: string | null; checkedAt: number | null }
interface ApiOptions { method?: 'GET' | 'POST' | 'PUT' | 'DELETE'; body?: unknown; audio?: Blob; signal?: AbortSignal; timeoutMs?: number }
export type Fetcher = (url: string, options: RequestInit) => Promise<Response>;
export type Requester = <T>(path: string, options?: ApiOptions) => Promise<T>;

const LOST = 'Connection lost. The run may still be active; reconnect before sending more commands.';
const TIMEOUT = 'Request timed out or was cancelled. Refresh to reconcile the stored run before retrying a control.';

/**
 * `uncertain` means the server may or may not have applied a mutation (lost
 * response, timeout, unreadable or gateway response). Never retry it blindly.
 */
export class ApiError extends Error {
  readonly status: number | null;
  readonly uncertain: boolean;
  constructor(message: string, status: number | null, uncertain: boolean) {
    super(message);
    this.status = status;
    this.uncertain = uncertain;
  }
}

export function isUncertain(error: unknown): boolean {
  return !(error instanceof ApiError) || error.uncertain;
}

export async function apiRequest<T>(path: string, options: ApiOptions = {}, fetcher: Fetcher = fetch): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  options.signal?.addEventListener('abort', abort, { once: true });
  if (options.signal?.aborted) controller.abort();
  const timer = setTimeout(abort, options.timeoutMs ?? 10000);
  const method = options.method ?? 'GET';
  try {
    let response: Response;
    try { response = await fetcher(`/api${path}`, {
      method, cache: 'no-store', signal: controller.signal,
      headers: method !== 'GET' ? { 'Content-Type': options.audio?.type ?? 'application/json', 'X-Visto': 'local-console' } : undefined,
      body: options.audio ?? (options.body === undefined ? undefined : JSON.stringify(options.body)),
    }); } catch { throw new ApiError(LOST, null, true); }
    let value: unknown;
    try { value = await response.json(); } catch { throw new ApiError(`Invalid service response (HTTP ${response.status})`, response.status, true); }
    if (!response.ok) {
      const detail = typeof value === 'object' && value !== null && 'detail' in value && typeof value.detail === 'string'
        ? value.detail : null;
      // 500/502/504 may come from a proxy or a crash after partial work. A 503 on a
      // mutation can follow a partially recorded change (e.g. answer saved, run not).
      const uncertain = detail === null || [500, 502, 504].includes(response.status)
        || (method !== 'GET' && response.status === 503);
      throw new ApiError(detail ?? `Request failed (HTTP ${response.status})`, response.status, uncertain);
    }
    return value as T;
  } catch (error) {
    if (controller.signal.aborted) throw new ApiError(TIMEOUT, null, true);
    if (error instanceof ApiError) throw error;
    throw new ApiError(LOST, null, true);
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', abort);
  }
}

const LIMIT_KEYS: (keyof Limits)[] = ['wall_time_ms', 'max_actions', 'max_inferences', 'max_command_timeout_ms', 'max_observation_delay_ms'];

export type Platform = 'android' | 'ios';

export interface AttachedDevice {
  platform: Platform;
  serial: string;
  state: string;
  model: string | null;
  product: string | null;
  selectable: boolean;
}

export interface DeviceInventory { available: boolean; devices: AttachedDevice[]; error: string | null; notes: string[] }

// Ready words per platform: adb's for Android, simulator/device words for iOS.
const READY_STATES: Record<Platform, readonly string[]> = { android: ['device'], ios: ['booted', 'connected'] };
const PLATFORM_NAMES: Record<Platform, string> = { android: 'Android', ios: 'iOS' };

const SERIAL = /^[A-Za-z0-9._:-]{1,256}$/;

/** Validates GET /devices; unsafe entries are dropped, never rendered. */
export function parseDevices(value: unknown): DeviceInventory {
  if (typeof value !== 'object' || value === null) throw new Error('Invalid device list response.');
  const v = value as Record<string, unknown>;
  const raw = Array.isArray(v.devices) ? v.devices : [];
  const devices = raw.flatMap((item): AttachedDevice[] => {
    if (typeof item !== 'object' || item === null) return [];
    const d = item as Record<string, unknown>;
    const platform = d.platform;
    if (platform !== 'android' && platform !== 'ios') return [];
    if (typeof d.serial !== 'string' || !SERIAL.test(d.serial) || typeof d.state !== 'string') return [];
    return [{
      platform, serial: d.serial, state: d.state,
      model: typeof d.model === 'string' ? d.model : null,
      product: typeof d.product === 'string' ? d.product : null,
      selectable: d.selectable === true && READY_STATES[platform].includes(d.state),
    }];
  });
  const notes = Array.isArray(v.notes) ? v.notes.filter((note): note is string => typeof note === 'string').slice(0, 16) : [];
  return { available: v.available === true, devices, error: typeof v.error === 'string' ? v.error : null, notes };
}

const STATE_HINTS: Record<Platform, Record<string, string>> = {
  android: {
    unauthorized: 'not authorized: accept the USB debugging prompt on the phone',
    offline: 'offline: reconnect the cable or restart adb',
    'no permissions': 'no permissions for this USB device',
  },
  // A run never boots a simulator, so a shut-down one must be started first.
  ios: {
    shutdown: 'not booted: start the simulator from Xcode first',
    unavailable: 'unavailable: not usable from this Mac, check it in Xcode',
  },
};

export function deviceLabel(device: AttachedDevice): string {
  const id = device.model ? `${device.model} (${device.serial})` : device.serial;
  const name = `${id} · ${PLATFORM_NAMES[device.platform]}`;
  return device.selectable ? name : `${name} — ${STATE_HINTS[device.platform][device.state] ?? device.state}`;
}

/** What to do when no device is listed; iOS is mentioned only where the server offers it. */
export function emptyDeviceHint(platforms: Platform[]): string {
  const ios = platforms.includes('ios') ? ', or boot an iOS simulator from Xcode' : '';
  return `Connect an Android phone with USB debugging enabled${ios}, then press Refresh.`;
}

/** Keep a still-selectable choice; otherwise preselect the only selectable device. */
export function reconcileDevice(current: string, devices: AttachedDevice[]): string {
  const selectable = devices.filter((device) => device.selectable);
  if (selectable.some((device) => device.serial === current)) return current;
  return selectable.length === 1 ? selectable[0].serial : '';
}

/** Validates the readiness payload; throws on a shape this console does not understand. */
export function parseReadiness(value: unknown): Readiness {
  const v = value as Partial<Readiness> | null;
  const nullableText = (x: unknown) => x === null || typeof x === 'string';
  if (typeof v !== 'object' || v === null || Array.isArray(v)
    || typeof v.configured !== 'boolean' || typeof v.provider_key_configured !== 'boolean'
    || typeof v.execution_available !== 'boolean' || !nullableText(v.configuration_error)
    || !nullableText(v.model) || !nullableText(v.appium_url) || !nullableText(v.active_run_id)
    || typeof v.default_limits !== 'object' || v.default_limits === null
    || LIMIT_KEYS.some((key) => !Number.isInteger((v.default_limits as Limits)[key]))) {
    throw new Error('Invalid readiness response');
  }
  const attention = Array.isArray(v.cleanup_attention_run_ids)
    ? v.cleanup_attention_run_ids.filter((id): id is string => typeof id === 'string') : [];
  const models = Array.isArray(v.models) ? v.models.filter((m): m is string => typeof m === 'string' && /\S/.test(m)) : [];
  if (models.length === 0 && typeof v.model === 'string') models.push(v.model);
  const platforms = Array.isArray(v.platforms)
    ? v.platforms.filter((p): p is Platform => typeof p === 'string' && Object.hasOwn(PLATFORM_NAMES, p)) : [];
  return { ...v, models, platforms, device_selection: 'manual', devices: Array.isArray(v.devices) ? v.devices : [], cleanup_attention_run_ids: attention } as Readiness;
}

/** Keep a still-offered model choice; otherwise use the server default. */
export function reconcileModel(current: string, readiness: Readiness): string {
  if (readiness.models.includes(current)) return current;
  return readiness.model && readiness.models.includes(readiness.model) ? readiness.model : readiness.models[0] ?? '';
}

/** A run this console does not own (terminal or from a prior process) may be deleted. */
export function canDeleteRun(run: Run, activeRunId: string | null): boolean {
  return run.run_id !== activeRunId && (run.state === 'terminal' || run.interrupted);
}

export function canCreateRun(readiness: Readiness | null, connected: boolean): boolean {
  return connected && readiness?.configured === true && readiness.execution_available === true;
}

/** Plain-language reason a new run cannot start, or null when it can. */
export function createBlockReason(readiness: Readiness | null, connected: boolean): string | null {
  if (!connected || !readiness) return 'The local service is not reachable. Start it, then check again.';
  if (!readiness.provider_key_configured) return 'No AI provider key is configured on the server.';
  if (!readiness.configured) return readiness.configuration_error ?? 'Server configuration is incomplete.';
  if (readiness.active_run_id) return 'Another run is still open. Finish or cancel it before starting a new one.';
  if (!readiness.execution_available) return 'The service is not accepting new runs right now.';
  return null;
}

export function outcome(run: Run): { label: string; tone: string } {
  if (run.interrupted) return { label: 'Not controlled here', tone: 'warning' };
  if (run.terminal?.kind === 'ai_conclusion') {
    const verdict = run.terminal.assessment?.verdict ?? 'unknown';
    return { label: `AI ${verdict}`, tone: verdict === 'passed' ? 'success' : verdict === 'failed' ? 'danger' : 'warning' };
  }
  const terminals: Record<string, string> = { infrastructure_failure: 'Infrastructure failure', cancelled: 'Cancelled', budget_exhausted: 'Budget exhausted' };
  if (run.terminal) return { label: terminals[run.terminal.kind] ?? run.terminal.kind, tone: run.terminal.kind === 'infrastructure_failure' ? 'danger' : 'warning' };
  const states = { created: 'Starting', running: 'Running', paused: 'Paused', waiting_for_user: 'Waiting for you', terminal: 'Terminal' };
  return { label: states[run.state], tone: run.state === 'running' || run.state === 'created' ? 'active' : 'neutral' };
}

export function safeScreenshotUrl(url: unknown, runId: string): string | null {
  if (typeof url !== 'string') return null;
  const prefix = `/api/runs/${encodeURIComponent(runId)}/artifacts/`;
  if (!url.startsWith(prefix)) return null;
  const suffix = url.slice(prefix.length);
  return /^[a-zA-Z0-9_-]+$/.test(suffix) ? url : null;
}

const PAGE = 100;
const MAX_PAGES = 50;

export function createRunMonitor(runId: string, publish: (snapshot: Snapshot) => void, request: Requester = apiRequest) {
  let snapshot: Snapshot = { run: null, events: [], connected: false, error: null, checkedAt: null };
  let generation = 0;
  let after = 0;
  let disposed = false;
  let active: AbortController | undefined;
  const path = `/runs/${encodeURIComponent(runId)}`;
  type Page = { events: RunEvent[]; next_after: number };
  return {
    async refresh(): Promise<boolean> {
      if (disposed) return false;
      const current = ++generation;
      active?.abort();
      const controller = new AbortController();
      active = controller;
      const stale = () => disposed || current !== generation;
      try {
        const [run, first] = await Promise.all([
          request<Run>(path, { signal: controller.signal }),
          request<Page>(`${path}/events?after=${after}&limit=${PAGE}`, { signal: controller.signal }),
        ]);
        if (stale()) return false;
        if (run.run_id !== runId) throw new Error('Invalid run response.');
        const events = new Map(snapshot.events.map((event) => [event.sequence, event]));
        let cursor = after;
        const accept = (page: Page) => {
          if (!Array.isArray(page.events) || !Number.isInteger(page.next_after) || page.next_after < cursor) throw new Error('Invalid run history response.');
          for (const event of page.events) {
            if (!Number.isInteger(event.sequence) || event.sequence < 1 || event.sequence > page.next_after) throw new Error('Invalid event sequence.');
            events.set(event.sequence, event);
          }
          cursor = page.next_after;
        };
        accept(first);
        // A full page means more history; a terminal run needs one read after
        // the terminal snapshot because the first page was fetched concurrently.
        let page = first;
        let finalRead = run.state !== 'terminal';
        for (let count = 1; count < MAX_PAGES && (page.events.length >= PAGE || !finalRead); count += 1) {
          if (page.events.length < PAGE) finalRead = true;
          page = await request<Page>(`${path}/events?after=${cursor}&limit=${PAGE}`, { signal: controller.signal });
          if (stale()) return false;
          accept(page);
        }
        after = cursor;
        snapshot = { run: snapshot.run && snapshot.run.revision > run.revision ? snapshot.run : run,
          events: [...events.values()].sort((a, b) => a.sequence - b.sequence), connected: true, error: null, checkedAt: Date.now() };
        publish(snapshot);
        return true;
      } catch {
        if (stale()) return false;
        snapshot = { ...snapshot, connected: false, error: 'Live updates disconnected. Stored evidence is retained below. The run may still be active; reconnect before sending controls.' };
        publish(snapshot);
        return false;
      }
    },
    acceptRun(run: Run): void {
      if (disposed || run.run_id !== runId) return;
      generation += 1;
      active?.abort();
      snapshot = { ...snapshot, run: snapshot.run && snapshot.run.revision > run.revision ? snapshot.run : run };
      publish(snapshot);
    },
    dispose(): void { disposed = true; generation += 1; active?.abort(); },
  };
}

/** Delay before the next automatic read, or null to stop polling. Reads only. */
export function pollDelay(snapshot: Snapshot, failures: number): number | null {
  if (!snapshot.connected) return Math.min(1000 * 2 ** Math.max(0, failures), 10000);
  const run = snapshot.run;
  if (!run) return 1000;
  if (run.state === 'terminal' || run.interrupted) return null;
  if (run.control_pending) return 1000;
  if (run.state === 'paused' || run.state === 'waiting_for_user') return 2000;
  return 1000;
}

export interface ControlAvailability { pause: boolean; resume: boolean; cancel: boolean; answer: boolean }

/** Control availability from stored lifecycle; busy/uncertain blocks every mutation. */
export function controlAvailability(run: Run | null, connected: boolean, busy: boolean, uncertain: boolean): ControlAvailability {
  const none = { pause: false, resume: false, cancel: false, answer: false };
  if (!run || !connected || busy || uncertain || run.interrupted || run.state === 'terminal') return none;
  const question = run.pending_question;
  return {
    pause: run.control_pending === null && (run.state === 'created' || run.state === 'running'),
    resume: run.can_resume === true,
    cancel: run.control_pending !== 'cancel',
    answer: run.control_pending === null && run.state === 'waiting_for_user' && question !== null
      && question.answer === null && question.cancelled_at === null,
  };
}

/**
 * Whether to send resume after a confirmed answer. The refreshed run is authoritative (e.g. the run
 * may have been cancelled meanwhile); the answer response is used only when the refresh failed.
 */
export function shouldResumeAfterAnswer(returned: Run, refreshed: Run | null): boolean {
  return (refreshed ?? returned).can_resume === true;
}

/**
 * Feedback after a confirmed answer when no resume is sent, chosen from the latest known run so it
 * only points to a Resume button that is actually shown.
 */
export function answerRecordedText(run: Run): string {
  if (run.state === 'terminal' || run.interrupted) return 'Answer recorded; the run has ended.';
  if (run.control_pending === 'cancel') return 'Answer recorded; the run is being cancelled.';
  if (run.state === 'created' || run.state === 'running') return 'Answer recorded; the run is already running.';
  if (run.can_resume) return 'Answer recorded. Select Resume to let the AI continue.';
  return 'Answer recorded. The run cannot resume right now; Resume becomes available when it can.';
}

export function runIdFromHash(hash: string): string | null {
  const match = /^#run=([A-Za-z0-9][A-Za-z0-9._-]{0,127})$/.exec(hash);
  return match ? match[1] : null;
}
