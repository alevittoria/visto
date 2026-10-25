import { useState } from 'react';
import type { FormEvent } from 'react';
import { canCreateRun, createBlockReason, reconcileDevice } from '../console.ts';
import { DeviceSelect } from './DeviceSelect.tsx';
import { DictateButton } from './DictateButton.tsx';
import { appendTranscript } from '../speech.ts';
import type { Readiness } from '../console.ts';
import { buildRunRequest, displayLimit, LIMIT_FIELDS, pickDevice, TEXT_LIMITS } from '../form.ts';
import type { CreateRunRequest, FormErrors, RunForm } from '../form.ts';

interface Props {
  form: RunForm;
  onChange: (update: (form: RunForm) => RunForm) => void;
  readiness: Readiness | null;
  connected: boolean;
  submitting: boolean;
  uncertain: boolean;
  error: string | null;
  onSubmit: (request: CreateRunRequest) => void;
  onRefresh: () => void;
}

export function NewRunForm({ form, onChange, readiness, connected, submitting, uncertain, error, onSubmit, onRefresh }: Props) {
  const [errors, setErrors] = useState<FormErrors>({});
  const [draft, setDraft] = useState('');
  const blocked = createBlockReason(readiness, connected);
  const allowed = canCreateRun(readiness, connected) && !submitting && !uncertain;
  const set = <K extends keyof RunForm>(key: K, value: RunForm[K]) => onChange((current) => ({ ...current, [key]: value }));
  const canDictate = !!readiness?.provider_key_configured && connected;
  const dictate = (key: 'goal' | 'expectedResult', limit: number) => (text: string) =>
    onChange((current) => ({ ...current, [key]: appendTranscript(current[key], text, limit) }));

  function addConstraint() {
    if (!/\S/.test(draft) || form.constraints.length >= TEXT_LIMITS.constraints) return;
    set('constraints', [...form.constraints, draft]);
    setDraft('');
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!allowed) return;
    const withDraft = /\S/.test(draft) ? { ...form, constraints: [...form.constraints, draft] } : form;
    const result = buildRunRequest(withDraft);
    setErrors(result.errors ?? {});
    if (result.request) {
      if (withDraft !== form) { onChange(() => withDraft); setDraft(''); }
      onSubmit(result.request);
    }
  }

  const describe = (id: string, hasError: boolean, extra?: string) =>
    [extra, hasError ? `${id}-error` : undefined].filter(Boolean).join(' ') || undefined;

  return (
    <form className="panel new-run" onSubmit={submit} noValidate aria-labelledby="new-run-title">
      <h1 id="new-run-title">New test run</h1>
      <p className="lead">Describe what to check. The AI looks at the screen, decides each step and gives its own verdict with the screenshots it relied on.</p>

      <div className="field">
        <label htmlFor="device">Device</label>
        <DeviceSelect value={form.deviceId} onSelect={(serial, devices) => onChange((current) => pickDevice(current, serial, devices))}
          onLoaded={(devices) => onChange((current) => pickDevice(current, reconcileDevice(current.deviceId, devices), devices))}
          invalid={!!errors.deviceId} describedBy={describe('device', !!errors.deviceId, 'device-status')}
          platforms={readiness?.platforms ?? []} />
        {errors.deviceId && <p id="device-error" className="error-text">{errors.deviceId}</p>}
      </div>

      <div className="field">
        <label htmlFor="model">AI model</label>
        <select id="model" value={form.model} onChange={(e) => set('model', e.target.value)}
          disabled={!readiness || readiness.models.length === 0} aria-describedby="model-help">
          {(readiness?.models ?? []).map((model) => (
            <option key={model} value={model}>{model}{model === readiness?.model ? ' (default)' : ''}</option>
          ))}
        </select>
        <p id="model-help" className="help">The model that observes the screen, decides each step and gives the verdict. Kept fixed for the whole run.</p>
      </div>

      <div className="field">
        <div className="label-row">
          <label htmlFor="goal">Goal</label>
          <DictateButton field="goal" disabled={!canDictate} onText={dictate('goal', TEXT_LIMITS.goal)} />
        </div>
        <textarea id="goal" rows={4} value={form.goal} onChange={(e) => set('goal', e.target.value)}
          aria-invalid={!!errors.goal} aria-describedby={describe('goal', !!errors.goal, 'goal-help')} />
        <p id="goal-help" className="help">Name the app and what to do. Use test data only. The goal stays fixed for the whole run. Dictated text is added at the end; review it before starting.</p>
        {errors.goal && <p id="goal-error" className="error-text">{errors.goal}</p>}
      </div>

      <div className="field">
        <div className="label-row">
          <label htmlFor="expected">Expected result <span className="optional">(optional)</span></label>
          <DictateButton field="expected result" disabled={!canDictate} onText={dictate('expectedResult', TEXT_LIMITS.expected)} />
        </div>
        <textarea id="expected" rows={2} value={form.expectedResult} onChange={(e) => set('expectedResult', e.target.value)}
          aria-invalid={!!errors.expectedResult} aria-describedby={describe('expected', !!errors.expectedResult)} />
        {errors.expectedResult && <p id="expected-error" className="error-text">{errors.expectedResult}</p>}
      </div>

      <fieldset className="field">
        <legend>Constraints <span className="optional">(optional)</span></legend>
        {form.constraints.length > 0 && (
          <ul className="constraints">
            {form.constraints.map((item, index) => (
              <li key={index}>
                <span>{item}</span>
                <button type="button" className="link" aria-label={`Remove constraint ${index + 1}`}
                  onClick={() => set('constraints', form.constraints.filter((_, i) => i !== index))}>Remove</button>
              </li>
            ))}
          </ul>
        )}
        <div className="inline">
          <label htmlFor="constraint" className="visually-hidden">New constraint</label>
          <input id="constraint" value={draft} placeholder="For example: do not submit payments" onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addConstraint(); } }}
            aria-describedby={errors.constraints ? 'constraints-error' : undefined} />
          <button type="button" className="secondary" onClick={addConstraint}
            disabled={!/\S/.test(draft) || form.constraints.length >= TEXT_LIMITS.constraints}>Add</button>
        </div>
        {errors.constraints && <p id="constraints-error" className="error-text">{errors.constraints}</p>}
      </fieldset>

      <div className="field checkbox">
        <input id="observe-only" type="checkbox" checked={form.observeOnly} onChange={(e) => set('observeOnly', e.target.checked)} aria-describedby="observe-help" />
        <label htmlFor="observe-only">Observe only</label>
        <p id="observe-help" className="help">The AI can take screenshots and judge, but cannot tap, swipe, type or navigate.</p>
      </div>

      <details className="limits">
        <summary>Limits</summary>
        <p className="help">The run stops when any limit is reached. Each limit is enforced by the service, not by the AI.</p>
        <div className="limit-grid">
          {LIMIT_FIELDS.map((field) => {
            const id = `limit-${field.key}`;
            const err = errors[field.key];
            return (
              <div className="field" key={field.key}>
                <label htmlFor={id}>{field.label}{field.unit === 'seconds' ? ' (seconds)' : ''}</label>
                <input id={id} inputMode="decimal" value={form.limits[field.key]}
                  onChange={(e) => onChange((current) => ({ ...current, limits: { ...current.limits, [field.key]: e.target.value } }))}
                  aria-invalid={!!err} aria-describedby={describe(id, !!err, `${id}-help`)} />
                <p id={`${id}-help`} className="help">{field.help} Range {displayLimit(field, field.min)}–{displayLimit(field, field.max)}.</p>
                {err && <p id={`${id}-error`} className="error-text">{err}</p>}
              </div>
            );
          })}
        </div>
      </details>

      <div className="notice" role="note">
        <strong>Before you start:</strong> starting a run sends screenshots of the device and your test text to the configured AI provider
        {form.observeOnly ? '.' : ', and lets the AI operate the device (taps, typing, navigation).'} Use a test device and synthetic data.
        Dictation sends your recording to the same provider for transcription; the audio is not stored here.
      </div>

      <div aria-live="polite" aria-atomic="true">
        {blocked && <p className="blocked">{blocked}</p>}
        {error && <p className="error-text" role="alert">{error}</p>}
      </div>
      <div className="actions">
        <button type="submit" disabled={!allowed} aria-disabled={!allowed}>{submitting ? 'Starting…' : 'Start run'}</button>
        {uncertain && <button type="button" className="secondary" onClick={onRefresh}>Refresh</button>}
      </div>
    </form>
  );
}
