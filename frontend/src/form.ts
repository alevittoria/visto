// New-run form state and conversion to the POST /api/runs request.
import type { AttachedDevice, Limits, Platform, Run } from './console.ts';

export interface LimitField {
  key: keyof Limits;
  label: string;
  help: string;
  unit: 'seconds' | 'count';
  min: number;
  max: number; // In request units (milliseconds or count).
}

// Bounds mirror the API contract; the server stays authoritative.
export const LIMIT_FIELDS: LimitField[] = [
  { key: 'wall_time_ms', label: 'Total time limit', help: 'The run stops when this time is used up.', unit: 'seconds', min: 1, max: 3600000 },
  { key: 'max_actions', label: 'Maximum device actions', help: 'Taps, swipes, typing and navigation presses.', unit: 'count', min: 1, max: 300 },
  { key: 'max_inferences', label: 'Maximum AI steps', help: 'Each step sends screenshots and history to the AI provider.', unit: 'count', min: 1, max: 300 },
  { key: 'max_command_timeout_ms', label: 'Time limit per action', help: 'Longest time one device action may take.', unit: 'seconds', min: 1, max: 60000 },
  { key: 'max_observation_delay_ms', label: 'Longest wait before looking again', help: 'Upper bound for the AI waiting for the screen to settle.', unit: 'seconds', min: 1, max: 60000 },
];

export const TEXT_LIMITS = { device: 256, goal: 16000, expected: 8000, constraint: 2000, constraints: 32 } as const;

export interface RunForm {
  deviceId: string;
  /** Platform of `deviceId`, set together via pickDevice; null until a device list has confirmed the pairing. */
  platform: Platform | null;
  model: string;
  goal: string;
  expectedResult: string;
  constraints: string[];
  observeOnly: boolean;
  limits: Record<keyof Limits, string>;
}

export interface CreateRunRequest {
  device_id: string;
  platform: Platform;
  model: string | null;
  goal: string;
  expected_result: string | null;
  constraints: string[];
  observe_only: boolean;
  limits: Limits;
}

export type FormErrors = Partial<Record<'deviceId' | 'goal' | 'expectedResult' | 'constraints' | keyof Limits, string>>;

export function displayLimit(field: LimitField, value: number): string {
  return field.unit === 'seconds' ? String(value / 1000) : String(value);
}

export function emptyForm(defaults: Limits): RunForm {
  const limits = {} as Record<keyof Limits, string>;
  for (const field of LIMIT_FIELDS) limits[field.key] = displayLimit(field, defaults[field.key]);
  return { deviceId: '', platform: null, model: '', goal: '', expectedResult: '', constraints: [], observeOnly: false, limits };
}

/**
 * Prefills a new form with a stored run's goal, model, mode and limits so the operator can
 * review and start it again. The device is kept only if it is still listed (DeviceChip
 * reconciles it); a model no longer offered falls back to the server default.
 */
export function formFromRun(run: Run, models: readonly string[], defaults: Limits): RunForm {
  const limits = {} as Record<keyof Limits, string>;
  for (const field of LIMIT_FIELDS) {
    const value = run.configuration?.limits?.[field.key];
    limits[field.key] = displayLimit(field, typeof value === 'number' && Number.isFinite(value) ? value : defaults[field.key]);
  }
  const model = run.configuration?.identity?.model ?? '';
  return {
    deviceId: run.device_id ?? '',
    platform: null, // Not stored on the run; pickDevice sets it once the device list confirms the device.
    model: models.includes(model) ? model : '',
    goal: run.goal?.text ?? '',
    expectedResult: run.goal?.expected_result ?? '',
    constraints: Array.isArray(run.goal?.constraints) ? [...run.goal.constraints] : [],
    observeOnly: Array.isArray(run.configuration?.capabilities) && run.configuration.capabilities.length === 0,
    limits,
  };
}

/** Sets the device and its platform together so a request can never pair them wrongly. */
export function pickDevice(form: RunForm, serial: string, devices: readonly AttachedDevice[]): RunForm {
  const device = devices.find((d) => d.serial === serial);
  return { ...form, deviceId: serial, platform: device?.platform ?? null };
}

/** Replaces limit text with server defaults only for fields the operator has not edited. */
export function applyDefaultLimits(form: RunForm, previous: Limits, next: Limits): RunForm {
  const limits = { ...form.limits };
  for (const field of LIMIT_FIELDS) {
    if (limits[field.key] === displayLimit(field, previous[field.key])) limits[field.key] = displayLimit(field, next[field.key]);
  }
  return { ...form, limits };
}

function parseLimit(field: LimitField, raw: string): number | string {
  const text = raw.trim();
  if (!/^\d+(\.\d+)?$/.test(text)) return 'Enter a positive number.';
  const parsed = Number(text);
  const value = field.unit === 'seconds' ? Math.round(parsed * 1000) : parsed;
  if (!Number.isSafeInteger(value)) return field.unit === 'count' ? 'Enter a whole number.' : 'Enter a valid number of seconds.';
  const lo = displayLimit(field, field.min);
  const hi = displayLimit(field, field.max);
  if (field.unit === 'count' && !Number.isInteger(parsed)) return 'Enter a whole number.';
  if (value < field.min || value > field.max) return field.unit === 'seconds' ? `Use between ${lo} and ${hi} seconds.` : `Use between ${lo} and ${hi}.`;
  return value;
}

const blank = (value: string) => !/\S/.test(value);
// Server limits count code points, not UTF-16 units.
const chars = (value: string) => [...value].length;

/** Validates the form; returns either a request body or per-field errors. */
export function buildRunRequest(form: RunForm): { request: CreateRunRequest; errors: null } | { request: null; errors: FormErrors } {
  const errors: FormErrors = {};
  const deviceId = form.deviceId.trim();
  if (!deviceId) errors.deviceId = 'Select a connected, authorized device.';
  else if (chars(deviceId) > TEXT_LIMITS.device) errors.deviceId = `Use at most ${TEXT_LIMITS.device} characters.`;
  else if (form.platform === null) errors.deviceId = 'Wait for the device list to load, then select the device again.';
  if (blank(form.goal)) errors.goal = 'Describe what the AI should test.';
  else if (chars(form.goal) > TEXT_LIMITS.goal) errors.goal = `Use at most ${TEXT_LIMITS.goal} characters.`;
  if (chars(form.expectedResult) > TEXT_LIMITS.expected) errors.expectedResult = `Use at most ${TEXT_LIMITS.expected} characters.`;
  const constraints = form.constraints.filter((item) => !blank(item));
  if (constraints.length > TEXT_LIMITS.constraints) errors.constraints = `Use at most ${TEXT_LIMITS.constraints} constraints.`;
  else if (constraints.some((item) => chars(item) > TEXT_LIMITS.constraint)) errors.constraints = `Each constraint may have at most ${TEXT_LIMITS.constraint} characters.`;
  const limits = {} as Limits;
  for (const field of LIMIT_FIELDS) {
    const value = parseLimit(field, form.limits[field.key] ?? '');
    if (typeof value === 'string') errors[field.key] = value;
    else limits[field.key] = value;
  }
  if (Object.keys(errors).length > 0) return { request: null, errors };
  return {
    errors: null,
    request: {
      device_id: deviceId,
      platform: form.platform!,
      // Blank means the server default model.
      model: blank(form.model) ? null : form.model.trim(),
      // Goal text is preserved verbatim; only an all-whitespace value is rejected.
      goal: form.goal,
      expected_result: blank(form.expectedResult) ? null : form.expectedResult,
      constraints,
      observe_only: form.observeOnly,
      limits,
    },
  };
}
