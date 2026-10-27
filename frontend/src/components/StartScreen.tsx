import { useEffect, useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import { canCreateRun, DEFAULT_LIMITS, reconcileDevice } from '../console.ts';
import type { AttachedDevice, Readiness } from '../console.ts';
import { buildRunRequest, LIMIT_FIELDS, pickDevice, TEXT_LIMITS } from '../form.ts';
import type { CreateRunRequest, FormErrors, RunForm } from '../form.ts';
import { appendTranscript } from '../speech.ts';
import { changedOptionCount, startNotices } from '../start.ts';
import { DeviceChip } from './DeviceChip.tsx';
import { DictateButton } from './DictateButton.tsx';
import { OptionsPanel } from './OptionsPanel.tsx';

interface Props {
  form: RunForm;
  onChange: (update: (form: RunForm) => RunForm) => void;
  readiness: Readiness | null;
  connected: boolean;
  /** True once the first readiness request has finished, whatever its result. */
  checked: boolean;
  submitting: boolean;
  uncertain: boolean;
  error: string | null;
  onSubmit: (request: CreateRunRequest) => void;
  onRefresh: () => void;
  onOpenSettings: () => void;
  onOpenRun: (runId: string) => void;
}

type ErrorKey = keyof FormErrors;

// Visual order of the fields, with the element that receives focus for each error.
const FOCUS_ORDER: { key: ErrorKey; id: string; inOptions: boolean }[] = [
  { key: 'goal', id: 'goal', inOptions: false },
  { key: 'deviceId', id: 'device', inOptions: false },
  { key: 'expectedResult', id: 'expected', inOptions: true },
  { key: 'constraints', id: 'constraint', inOptions: true },
  ...LIMIT_FIELDS.map((field) => ({ key: field.key, id: `limit-${field.key}`, inOptions: true })),
];

const OPTIONS_ID = 'run-options';

/** Prompt-first start screen: write the goal, press Enter. */
export function StartScreen({ form, onChange, readiness, connected, checked, submitting, uncertain, error, onSubmit, onRefresh, onOpenSettings, onOpenRun }: Props) {
  const [errors, setErrors] = useState<FormErrors>({});
  const [draft, setDraft] = useState('');
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [focusId, setFocusId] = useState<string | null>(null);
  const optionsTrigger = useRef<HTMLButtonElement>(null);
  /** The device the operator picked in the menu; a listing never swaps it for another device. */
  const chosen = useRef<string | null>(null);

  const allowed = canCreateRun(readiness, connected) && !submitting && !uncertain;
  const canDictate = !!readiness?.provider_key_configured && connected;
  // Until the first readiness request finishes, say so instead of reporting the service as unreachable.
  const connecting = !connected && !checked;
  const notices = connecting ? [] : startNotices(readiness, connected);
  const changed = changedOptionCount(form, readiness?.default_limits ?? DEFAULT_LIMITS, readiness?.model ?? null, draft);

  useEffect(() => {
    if (focusId === null) return;
    document.getElementById(focusId)?.focus();
    setFocusId(null);
  }, [focusId]);

  function onLoaded(devices: AttachedDevice[]) {
    const pick = chosen.current;
    onChange((current) => {
      // After an explicit choice, keep that device while it is ready and leave the choice empty
      // otherwise: never switch to a device the operator did not pick.
      const serial = pick === null
        ? reconcileDevice(current.deviceId, devices)
        : devices.some((d) => d.serial === pick && d.selectable) ? pick : '';
      return pickDevice(current, serial, devices);
    });
  }

  function onSelectDevice(serial: string, devices: AttachedDevice[]) {
    chosen.current = serial;
    onChange((current) => pickDevice(current, serial, devices));
  }

  function closeOptions() {
    setOptionsOpen(false);
    optionsTrigger.current?.focus();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!allowed) return;
    const withDraft = /\S/.test(draft) ? { ...form, constraints: [...form.constraints, draft] } : form;
    const result = buildRunRequest(withDraft);
    const nextErrors = result.errors ?? {};
    setErrors(nextErrors);
    if (result.request) {
      if (withDraft !== form) { onChange(() => withDraft); setDraft(''); }
      onSubmit(result.request);
      return;
    }
    const first = FOCUS_ORDER.find((item) => nextErrors[item.key]);
    if (first) {
      if (first.inOptions) setOptionsOpen(true);
      setFocusId(first.id);
    }
  }

  function onGoalKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter starts; Shift+Enter is a newline; an IME composition keeps its own Enter.
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  const goalDescribedBy = ['goal-help', errors.goal ? 'goal-error' : null].filter(Boolean).join(' ');

  return (
    <form className="start" onSubmit={submit} noValidate aria-labelledby="start-title">
      <h1 id="start-title" className="start-title">What do you want to test?</h1>
      <p className="start-subtitle">Name the app and what to check, then press Enter. The AI looks at the screen, decides each step and gives its own verdict.</p>

      <div className="start-notices" role="status" aria-live="polite" aria-atomic="true">
        {connecting && <p className="start-connecting">Connecting to the local service…</p>}
        {notices.map((notice) => (
          <p key={notice.text} className={notice.tone === 'blocked' ? 'blocked' : 'start-warning'}>
            {notice.text}
            {notice.action && (
              <button type="button" className="link" onClick={() => {
                const action = notice.action!;
                if (action.target === 'settings') onOpenSettings();
                else if (action.runId) onOpenRun(action.runId);
              }}>{notice.action.label}</button>
            )}
          </p>
        ))}
      </div>

      <div className={`composer${errors.goal ? ' invalid' : ''}`}>
        <label htmlFor="goal" className="visually-hidden">Goal</label>
        <textarea id="goal" rows={3} autoFocus value={form.goal} onKeyDown={onGoalKeyDown}
          onChange={(e) => onChange((current) => ({ ...current, goal: e.target.value }))}
          placeholder="In Pantry Notes, add “milk” to the list and check it appears"
          aria-invalid={!!errors.goal} aria-describedby={goalDescribedBy} />
        <p id="goal-help" className="visually-hidden">
          Enter starts the run; Shift+Enter adds a new line. Use test data only. The goal stays fixed for the whole run.
          Dictated text is added at the end; review it before starting.
        </p>
        <div className="composer-bar">
          <DeviceChip value={form.deviceId} onSelect={onSelectDevice} onLoaded={onLoaded}
            invalid={!!errors.deviceId} describedBy={errors.deviceId ? 'device-error' : undefined}
            platforms={readiness?.platforms ?? []} pollingAllowed={connected && readiness !== null && !readiness.active_run_id} />
          <button type="button" ref={optionsTrigger} className={`chip${changed > 0 ? ' changed' : ''}`}
            aria-expanded={optionsOpen} aria-controls={OPTIONS_ID} onClick={() => setOptionsOpen(!optionsOpen)}>
            {changed > 0 ? `Options · ${changed} changed` : 'Options'}
          </button>
          <span className="composer-spacer" />
          <DictateButton field="goal" disabled={!canDictate}
            onText={(text) => onChange((current) => ({ ...current, goal: appendTranscript(current.goal, text, TEXT_LIMITS.goal) }))} />
          <button type="submit" className="start-button" disabled={!allowed} aria-disabled={!allowed}>
            {submitting ? 'Starting…' : 'Start'}
          </button>
        </div>
      </div>

      <div className="start-feedback" aria-live="polite" aria-atomic="true">
        {errors.goal && <p id="goal-error" className="error-text">{errors.goal}</p>}
        {errors.deviceId && <p id="device-error" className="error-text">{errors.deviceId}</p>}
        {error && <p className="error-text" role="alert">{error}</p>}
        {uncertain && <button type="button" className="secondary small" onClick={onRefresh}>Refresh</button>}
      </div>

      <OptionsPanel id={OPTIONS_ID} hidden={!optionsOpen} form={form} onChange={onChange} readiness={readiness} errors={errors}
        draft={draft} onDraft={setDraft} canDictate={canDictate} onClose={closeOptions} />

      <div className="privacy" role="note">
        <p>
          Starting sends screenshots and your test text to the AI provider{form.observeOnly ? '' : ' and lets the AI operate the device'}.
          Use a test device and synthetic data.
        </p>
        <details>
          <summary>Privacy details</summary>
          <p>
            Starting a run sends screenshots of the device and your test text to the configured AI provider
            {form.observeOnly ? '.' : ', and lets the AI operate the device (taps, typing, navigation).'} Use a test device and synthetic data.
            Dictation sends your recording to the same provider for transcription; the audio is not stored here.
          </p>
        </details>
      </div>
    </form>
  );
}
