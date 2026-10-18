// Dictated goal text: record in the browser, transcribe on the server, let the operator review it.
import { apiRequest } from './console.ts';
import type { Requester } from './console.ts';

/** Recording formats the transcription endpoint accepts, in preference order. */
export const RECORDING_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'] as const;
/** Each recording stops automatically after this long; it keeps uploads small. */
export const MAX_RECORDING_MS = 120000;

export interface Transcript { text: string; model: string }

/** First supported recording type, or null when this browser cannot record a compatible format. */
export function pickRecordingType(isSupported: (type: string) => boolean): string | null {
  return RECORDING_TYPES.find((type) => isSupported(type)) ?? null;
}

/** True when the page may ask for the microphone and record audio. */
export function canDictate(env: { isSecureContext?: boolean; mediaDevices?: unknown; MediaRecorder?: unknown }): boolean {
  return env.isSecureContext === true && typeof env.mediaDevices === 'object' && env.mediaDevices !== null
    && typeof env.MediaRecorder === 'function';
}

/** Appends dictated text to what the operator already typed, keeping one separating space. */
export function appendTranscript(current: string, text: string, limit: number): string {
  const addition = text.trim();
  if (!addition) return current;
  const joined = /\S$/.test(current) ? `${current} ${addition}` : current + addition;
  return joined.slice(0, limit);
}

/** Sends one recording to POST /api/transcriptions and validates the reply. */
export async function transcribe(recording: Blob, request: Requester = apiRequest): Promise<Transcript> {
  const value = await request<unknown>('/transcriptions', { method: 'POST', audio: recording, timeoutMs: 75000 });
  const v = value as Partial<Transcript> | null;
  if (typeof v !== 'object' || v === null || typeof v.text !== 'string' || typeof v.model !== 'string') {
    throw new Error('Invalid transcription response.');
  }
  return { text: v.text, model: v.model };
}
