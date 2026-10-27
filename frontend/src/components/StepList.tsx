import { useState } from 'react';
import type { KeyboardEvent } from 'react';
import { EFFECT_LABELS } from '../history.ts';
import type { ObservationEntry } from '../history.ts';
import type { Step } from '../steps.ts';
import { Entry } from './EvidenceHistory.tsx';

/** Icon glyphs for the AI's own effect judgements; the text label is always given alongside. */
export const EFFECT_ICONS: Record<string, string> = { achieved: '✔', not_achieved: '✖', unclear: '?' };

/** Icon plus screen-reader label for one AI effect judgement. */
export function EffectMark({ verdict }: { verdict: string }) {
  const label = EFFECT_LABELS[verdict] ?? verdict;
  return (
    <span className={`effect-mark ${verdict}`} title={label}>
      <span aria-hidden="true">{EFFECT_ICONS[verdict] ?? '•'}</span>
      <span className="visually-hidden">{label}</span>
    </span>
  );
}

function StepStatus({ step, ended }: { step: Step; ended: boolean }) {
  if (step.effect === 'achieved' || step.effect === 'not_achieved' || step.effect === 'unclear') return <EffectMark verdict={step.effect} />;
  if (step.effect === 'pending') {
    const label = ended ? 'Not judged by the AI' : 'Waiting for the AI to judge';
    return (
      <span className="effect-mark pending" title={label}>
        <span aria-hidden="true">…</span>
        <span className="visually-hidden">{label}</span>
      </span>
    );
  }
  // Rejected, failed or uncertain receipts are technical outcomes, shown instead of an effect.
  if (step.receipt && step.receipt.status !== 'completed') return <span className={`step-receipt ${step.receipt.status}`}>{step.receipt.label}</span>;
  return null;
}

interface Props { steps: Step[]; observations: Map<string, ObservationEntry>; ended: boolean }

/** Compact list of AI steps, newest first; each row expands to every record of that step. */
export function StepList({ steps, observations, ended }: Props) {
  const [open, setOpen] = useState<ReadonlySet<number>>(() => new Set());
  const toggle = (number: number) => setOpen((current) => {
    const next = new Set(current);
    if (next.has(number)) next.delete(number); else next.add(number);
    return next;
  });
  const collapseOnEscape = (number: number) => (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Escape') return;
    event.stopPropagation();
    toggle(number);
    document.getElementById(`step-toggle-${number}`)?.focus();
  };

  return (
    <section className="panel steps" aria-labelledby="steps-title">
      <h2 id="steps-title">Steps</h2>
      {steps.length === 0 ? <p className="muted">Waiting for the first AI step</p> : (
        <ol className="step-list" reversed>
          {[...steps].reverse().map((step) => {
            const expanded = open.has(step.number);
            const panelId = `step-records-${step.number}`;
            return (
              <li key={step.number} className={`step${expanded ? ' expanded' : ''}`}>
                <button type="button" id={`step-toggle-${step.number}`} className="step-row" aria-expanded={expanded} aria-controls={expanded ? panelId : undefined}
                  onClick={() => toggle(step.number)}>
                  <span className="step-number"><span className="visually-hidden">Step </span>{step.number}</span>
                  {step.thumbnail?.url
                    ? <img className="step-thumb" src={step.thumbnail.url} alt="" loading="lazy" />
                    : <span className="step-thumb empty" aria-hidden="true" />}
                  <span className="step-summary">{step.summary}</span>
                  <StepStatus step={step} ended={ended} />
                  <span className="step-chevron" aria-hidden="true" />
                </button>
                {expanded && (
                  <div id={panelId} className="step-records" onKeyDown={collapseOnEscape(step.number)}>
                    {step.effectExplanation && <p className={`effect-line ${step.effect}`}><strong>{EFFECT_LABELS[step.effect] ?? step.effect}:</strong> {step.effectExplanation}</p>}
                    <ol className="timeline">
                      {step.records.map((entry) => (
                        <li key={entry.sequence} className={`entry ${entry.type}`}><Entry entry={entry} observations={observations} /></li>
                      ))}
                    </ol>
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
