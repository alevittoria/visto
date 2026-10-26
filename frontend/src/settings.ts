/** Console settings: GET/PUT /api/settings and the write-only provider key routes. */
import { ApiError, apiRequest } from './console.ts';
import type { Fetcher } from './console.ts';

export interface IosSettings { team_id: string; signing_id: string; wda_bundle_id: string; prebuilt_wda: boolean; wda_derived_data: string }
export interface KeyStatus { configured: boolean; last4: string | null; storage: 'file' }
export interface SettingsView {
  price_refresh: boolean;
  ios_supported: boolean;
  ios: IosSettings | null;
  key: KeyStatus;
  wda_project: string | null;
  wda_rebuild_needed: boolean;
}
export type VerifyResult = 'ok' | 'missing' | 'unauthorized' | 'model_unavailable' | 'unreachable';
export interface SettingsBody { price_refresh: boolean; ios: IosSettings | null }

const VERIFY_RESULTS: readonly string[] = ['ok', 'missing', 'unauthorized', 'model_unavailable', 'unreachable'];
const IOS_TEXT = ['team_id', 'signing_id', 'wda_bundle_id', 'wda_derived_data'] as const;

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);

export function parseKeyStatus(value: unknown): KeyStatus | null {
  if (!isObject(value) || typeof value.configured !== 'boolean' || value.storage !== 'file') return null;
  const { last4 } = value;
  if (last4 !== null && (typeof last4 !== 'string' || last4.length > 4)) return null;
  if (!value.configured && last4 !== null) return null;
  return { configured: value.configured, last4: last4 as string | null, storage: 'file' };
}

function parseIos(value: unknown): IosSettings | null {
  if (!isObject(value) || typeof value.prebuilt_wda !== 'boolean') return null;
  if (!IOS_TEXT.every((name) => typeof value[name] === 'string')) return null;
  return { team_id: value.team_id as string, signing_id: value.signing_id as string, wda_bundle_id: value.wda_bundle_id as string,
    prebuilt_wda: value.prebuilt_wda, wda_derived_data: value.wda_derived_data as string };
}

export function parseSettings(value: unknown): SettingsView | null {
  if (!isObject(value) || typeof value.price_refresh !== 'boolean' || typeof value.ios_supported !== 'boolean') return null;
  if (typeof value.wda_rebuild_needed !== 'boolean') return null;
  if (value.wda_project !== null && typeof value.wda_project !== 'string') return null;
  const key = parseKeyStatus(value.key);
  if (!key) return null;
  let ios: IosSettings | null = null;
  if (value.ios_supported) {
    ios = parseIos(value.ios);
    if (!ios) return null;
  } else if (value.ios !== null) return null;
  return { price_refresh: value.price_refresh, ios_supported: value.ios_supported, ios, key,
    wda_project: value.wda_project, wda_rebuild_needed: value.wda_rebuild_needed };
}

export function parseVerify(value: unknown): VerifyResult | null {
  if (!isObject(value) || typeof value.result !== 'string' || !VERIFY_RESULTS.includes(value.result)) return null;
  return value.result as VerifyResult;
}

export function settingsFromHash(hash: string): boolean {
  return hash === '#settings';
}

export function verifyMessage(result: VerifyResult): string {
  switch (result) {
    case 'ok': return 'The key works and the default model is available.';
    case 'missing': return 'No key is stored. Save a key first.';
    case 'unauthorized': return 'The provider rejected the key. Check that it is correct and active.';
    case 'model_unavailable': return 'The key is accepted, but the default model is not available to it.';
    case 'unreachable': return 'The provider could not be reached. Check the network connection and try again.';
  }
}

export function iosEdited(original: IosSettings, edited: IosSettings): boolean {
  return IOS_TEXT.some((name) => original[name] !== edited[name]) || original.prebuilt_wda !== edited.prebuilt_wda;
}

/**
 * Body for PUT /api/settings. iOS values are sent only when the user changed them:
 * a non-null `ios` re-records the installed XCUITest version and clears the rebuild warning.
 */
export function settingsBody(original: SettingsView, priceRefresh: boolean, ios: IosSettings | null): SettingsBody {
  const changed = original.ios !== null && ios !== null && iosEdited(original.ios, ios);
  return { price_refresh: priceRefresh, ios: changed ? ios : null };
}

async function parsed<T>(request: Promise<unknown>, parse: (value: unknown) => T | null): Promise<T> {
  const value = parse(await request);
  if (value === null) throw new ApiError('Invalid service response', null, true);
  return value;
}

export function loadSettings(signal?: AbortSignal, fetcher?: Fetcher): Promise<SettingsView> {
  return parsed(apiRequest<unknown>('/settings', { signal }, fetcher), parseSettings);
}

export function saveSettings(body: SettingsBody, fetcher?: Fetcher): Promise<SettingsView> {
  return parsed(apiRequest<unknown>('/settings', { method: 'PUT', body }, fetcher), parseSettings);
}

export function setKey(apiKey: string, fetcher?: Fetcher): Promise<KeyStatus> {
  return parsed(apiRequest<unknown>('/settings/key', { method: 'PUT', body: { api_key: apiKey } }, fetcher), parseKeyStatus);
}

export function deleteKey(fetcher?: Fetcher): Promise<KeyStatus> {
  return parsed(apiRequest<unknown>('/settings/key', { method: 'DELETE' }, fetcher), parseKeyStatus);
}

export function verifyKey(fetcher?: Fetcher): Promise<VerifyResult> {
  return parsed(apiRequest<unknown>('/settings/key/verify', { method: 'POST', timeoutMs: 20000 }, fetcher), parseVerify);
}
