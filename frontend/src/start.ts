// Pure decisions for the start screen: blocking notices, option summary, one-click rerun, device polling.
import { canCreateRun, createBlockReason } from './console.ts';
import type { AttachedDevice, Limits, Readiness, Run } from './console.ts';
import { buildRunRequest, displayLimit, formFromRun, LIMIT_FIELDS, pickDevice } from './form.ts';
import type { CreateRunRequest, RunForm } from './form.ts';

export type NoticeTone = 'blocked' | 'warning';
export interface StartNotice {
  tone: NoticeTone;
  text: string;
  action: { label: string; target: 'settings' | 'run'; runId?: string } | null;
}

/** Notices for the start screen; empty when a run can start and nothing needs attention. */
export function startNotices(readiness: Readiness | null, connected: boolean): StartNotice[] {
  const notices: StartNotice[] = [];
  const reason = createBlockReason(readiness, connected);
  if (reason !== null) {
    let action: StartNotice['action'] = null;
    if (connected && readiness) {
      if (!readiness.provider_key_configured || !readiness.configured) action = { label: 'Open settings', target: 'settings' };
      else if (readiness.active_run_id) action = { label: 'View open run', target: 'run', runId: readiness.active_run_id };
    }
    notices.push({ tone: 'blocked', text: reason, action });
  }
  const attention = readiness?.cleanup_attention_run_ids ?? [];
  if (connected && attention.length > 0) {
    notices.push({
      tone: 'warning',
      text: attention.length === 1
        ? 'Device cleanup failed after a finished run. Check the device before relying on it.'
        : `Device cleanup failed after ${attention.length} finished runs. Check the device before relying on it.`,
      action: { label: 'View run', target: 'run', runId: attention[0] },
    });
  }
  return notices;
}

const filled = (value: string) => /\S/.test(value);

/**
 * Number of optional settings changed from their defaults; the model counts only when it differs from the
 * server default. A non-blank constraint draft counts too, because Start sends it with the run.
 */
export function changedOptionCount(form: RunForm, defaults: Limits, defaultModel: string | null, constraintDraft = ''): number {
  let count = 0;
  if (filled(form.expectedResult)) count += 1;
  if (form.constraints.some(filled) || filled(constraintDraft)) count += 1;
  if (form.observeOnly) count += 1;
  if (filled(form.model) && form.model.trim() !== defaultModel) count += 1;
  for (const field of LIMIT_FIELDS) {
    if (form.limits[field.key].trim() !== displayLimit(field, defaults[field.key])) count += 1;
  }
  return count;
}

export type RerunPlan = { kind: 'create'; request: CreateRunRequest } | { kind: 'blocked'; reason: string };

/** Why the service cannot start a rerun now, or null when it can. Checked before listing devices. */
export function rerunServiceBlock(readiness: Readiness | null, connected: boolean): string | null {
  const reason = createBlockReason(readiness, connected);
  if (reason !== null || !readiness || !canCreateRun(readiness, connected)) {
    return reason ?? 'The service is not accepting new runs right now.';
  }
  return null;
}

/** Decides whether a stored run can start again unchanged. Checks run in a fixed order and the first failure wins. */
export function rerunPlan(run: Run, devices: AttachedDevice[], readiness: Readiness | null, connected: boolean, defaults: Limits): RerunPlan {
  const blocked = (reason: string): RerunPlan => ({ kind: 'blocked', reason });
  const serviceReason = rerunServiceBlock(readiness, connected);
  if (serviceReason !== null || !readiness) return blocked(serviceReason ?? 'The service is not accepting new runs right now.');
  const storedModel = run.configuration?.identity?.model ?? '';
  // A blank stored model means the server default.
  if (filled(storedModel) && !readiness.models.includes(storedModel)) {
    return blocked('The AI model used by this run is no longer offered. Use Edit and rerun to choose one.');
  }
  const device = devices.find((d) => d.serial === run.device_id);
  if (!device || !device.selectable) return blocked('The device used by this run is not ready. Use Edit and rerun to pick another one.');
  const form = pickDevice(formFromRun(run, readiness.models, defaults), run.device_id, devices);
  const built = buildRunRequest(form);
  if (built.request) return { kind: 'create', request: built.request };
  return blocked(Object.values(built.errors)[0] ?? 'This run cannot be started again unchanged.');
}

export interface PollInput { selectableCount: number; runOpen: boolean; pageVisible: boolean }
export const DEVICE_POLL_MS = 5000;

/**
 * Delay in ms before the next device list request, or null to stop polling. Polling continues only
 * while no device is selectable, no run is open and the page is visible. Callers treat a failed
 * list as `selectableCount: 0`, so the interval is kept after a failure.
 */
export function nextDevicePoll(input: PollInput): number | null {
  return input.selectableCount === 0 && !input.runOpen && input.pageVisible ? DEVICE_POLL_MS : null;
}
