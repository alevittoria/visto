import { EFFECT_LABELS } from '../history.ts';
import type { DecisionEntry, ObservationEntry } from '../history.ts';
import { ObservationThumb } from './EvidenceHistory.tsx';
import { EFFECT_ICONS } from './StepList.tsx';

interface Props { decision: DecisionEntry | null; source: ObservationEntry | undefined }

/** The AI's latest reasoning about the screen it last saw; replaces a live screenshot, which always lags. */
export function NowBlock({ decision, source }: Props) {
  return (
    <section className="panel now" aria-labelledby="now-title">
      <div className="now-layout">
        <div className="now-main">
          <h2 id="now-title" className="kicker">Latest AI reasoning</h2>
          {!decision && <p className="muted">Waiting for the first AI step</p>}
          {decision && (
            <>
              {decision.effect && (
                <p className={`now-effect ${decision.effect.verdict}`}>
                  <span className={`effect-mark ${decision.effect.verdict}`} aria-hidden="true">{EFFECT_ICONS[decision.effect.verdict] ?? '•'}</span>
                  <span><strong>Previous action: {EFFECT_LABELS[decision.effect.verdict] ?? decision.effect.verdict}.</strong> {decision.effect.explanation}</span>
                </p>
              )}
              <p className="now-rationale prewrap" tabIndex={0} role="region" aria-label="AI reasoning (scrollable)">{decision.rationale.trim() || 'No reasoning was given.'}</p>
              <p className="now-next">{decision.next}</p>
              {decision.planChanged && (
                <details className="now-plan">
                  <summary>Working plan updated</summary>
                  <p className="prewrap">{decision.workingPlan}</p>
                </details>
              )}
            </>
          )}
        </div>
        {decision && (
          <div className="now-shot">
            <ObservationThumb id={decision.sourceObservationId} entry={source} />
            <span className="help">Screen it reasoned about</span>
          </div>
        )}
      </div>
    </section>
  );
}
