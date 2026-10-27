import type { KeyboardEvent } from 'react';
import type { Readiness } from '../console.ts';
import { appendTranscript } from '../speech.ts';
import { displayLimit, LIMIT_FIELDS, TEXT_LIMITS } from '../form.ts';
import type { FormErrors, RunForm } from '../form.ts';
import { DictateButton } from './DictateButton.tsx';

interface Props {
  id: string;
  /** Collapsed panels stay mounted so the Options chip always controls an existing element. */
  hidden: boolean;
  form: RunForm;
  onChange: (update: (form: RunForm) => RunForm) => void;
  readiness: Readiness | null;
  errors: FormErrors;
  /** Unsaved constraint text; included in the request on start. */
  draft: string;
  onDraft: (value: string) => void;
  canDictate: boolean;
  onClose: () => void;
}

const describe = (id: string, hasError: boolean, extra?: string) =>
  [extra, hasError ? `${id}-error` : undefined].filter(Boolean).join(' ') || undefined;

/** Optional run settings: model, expected result, constraints, observe-only and limits. */
export function OptionsPanel({ id, hidden, form, onChange, readiness, errors, draft, onDraft, canDictate, onClose }: Props) {
  const set = <K extends keyof RunForm>(key: K, value: RunForm[K]) => onChange((current) => ({ ...current, [key]: value }));
  const canAdd = /\S/.test(draft) && form.constraints.length < TEXT_LIMITS.constraints;

  function addConstraint() {
    if (!canAdd) return;
    set('constraints', [...form.constraints, draft]);
    onDraft('');
  }

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onClose();
    }
  }

  return (
    <section className="options-panel" id={id} hidden={hidden} aria-labelledby={`${id}-title`} onKeyDown={onKeyDown}>
      <div className="options-head">
        <h2 id={`${id}-title`}>Options</h2>
        <button type="button" className="link" onClick={onClose}>Hide options</button>
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
          <label htmlFor="expected">Expected result <span className="optional">(optional)</span></label>
          <DictateButton field="expected result" disabled={!canDictate}
            onText={(text) => onChange((current) => ({ ...current, expectedResult: appendTranscript(current.expectedResult, text, TEXT_LIMITS.expected) }))} />
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
          <input id="constraint" value={draft} placeholder="For example: do not submit payments" onChange={(e) => onDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addConstraint(); } }}
            aria-invalid={!!errors.constraints} aria-describedby={errors.constraints ? 'constraints-error' : undefined} />
          <button type="button" className="secondary" onClick={addConstraint} disabled={!canAdd}>Add</button>
        </div>
        {errors.constraints && <p id="constraints-error" className="error-text">{errors.constraints}</p>}
      </fieldset>

      <div className="field checkbox">
        <input id="observe-only" type="checkbox" checked={form.observeOnly} onChange={(e) => set('observeOnly', e.target.checked)} aria-describedby="observe-help" />
        <label htmlFor="observe-only">Observe only</label>
        <p id="observe-help" className="help">The AI can take screenshots and judge, but cannot tap, swipe, type or navigate.</p>
      </div>

      <fieldset className="field options-limits">
        <legend>Limits</legend>
        <p className="help">The run stops when any limit is reached. Each limit is enforced by the service, not by the AI.</p>
        <div className="limit-grid">
          {LIMIT_FIELDS.map((field) => {
            const fieldId = `limit-${field.key}`;
            const err = errors[field.key];
            return (
              <div className="field" key={field.key}>
                <label htmlFor={fieldId}>{field.label}{field.unit === 'seconds' ? ' (seconds)' : ''}</label>
                <input id={fieldId} inputMode="decimal" value={form.limits[field.key]}
                  onChange={(e) => onChange((current) => ({ ...current, limits: { ...current.limits, [field.key]: e.target.value } }))}
                  aria-invalid={!!err} aria-describedby={describe(fieldId, !!err, `${fieldId}-help`)} />
                <p id={`${fieldId}-help`} className="help">{field.help} Range {displayLimit(field, field.min)}–{displayLimit(field, field.max)}.</p>
                {err && <p id={`${fieldId}-error`} className="error-text">{err}</p>}
              </div>
            );
          })}
        </div>
      </fieldset>
    </section>
  );
}
