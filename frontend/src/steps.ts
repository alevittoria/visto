// Pure projection of run history into AI steps (one step per decision).
// It never infers a test verdict: effects are only the AI's own judgements.
import type { ActionEntry, DecisionEntry, HistoryEntry, ObservationEntry, ReceiptEntry } from './history.ts';

export type StepEffect = 'achieved' | 'not_achieved' | 'unclear' | 'pending' | 'none';

export interface Step {
  number: number;
  decision: DecisionEntry | null;
  action: ActionEntry | null;
  receipt: ReceiptEntry | null;
  summary: string;
  effect: StepEffect;
  effectExplanation: string | null;
  thumbnail: ObservationEntry | null;
  records: HistoryEntry[];
}

const NON_ACTION_SUMMARY: Record<string, string> = {
  observe_after: 'Wait and look again',
  ask_user: 'Asked a question',
  conclude: 'Concluded',
};

function summarize(decision: DecisionEntry | null, action: ActionEntry | null): string {
  if (!decision) return 'Waiting for the first AI step';
  if (decision.nextKind === 'act') return action?.description ?? decision.next;
  return NON_ACTION_SUMMARY[decision.nextKind] ?? decision.next;
}

/** Effect of this step's action, as judged by the next decision for that same action. */
function judge(
  action: ActionEntry | null, receipt: ReceiptEntry | null, next: DecisionEntry | undefined,
): Pick<Step, 'effect' | 'effectExplanation'> {
  if (!action || (receipt && receipt.status !== 'completed')) return { effect: 'none', effectExplanation: null };
  const judgement = next?.effect;
  if (!judgement || judgement.action_id !== action.id) return { effect: 'pending', effectExplanation: null };
  return { effect: judgement.verdict, effectExplanation: judgement.explanation };
}

function build(
  number: number, records: HistoryEntry[], nextDecision: DecisionEntry | undefined, observations: Map<string, ObservationEntry>,
): Step {
  const decision = records.find((e): e is DecisionEntry => e.type === 'decision') ?? null;
  const action = records.find((e): e is ActionEntry => e.type === 'action') ?? null;
  const receipt = records.find((e): e is ReceiptEntry => e.type === 'receipt' && (!action || e.actionId === action.id)) ?? null;
  return {
    number, decision, action, receipt, records,
    summary: summarize(decision, action),
    ...judge(action, receipt, nextDecision),
    thumbnail: decision ? observations.get(decision.sourceObservationId) ?? null : null,
  };
}

/** Groups records under the decision that precedes them; oldest step first. */
export function groupSteps(entries: HistoryEntry[], observations: Map<string, ObservationEntry>): Step[] {
  const groups: HistoryEntry[][] = [];
  let leading: HistoryEntry[] = [];
  for (const entry of entries) {
    if (entry.type === 'decision') {
      groups.push([...leading, entry]);
      leading = [];
    } else if (groups.length) groups[groups.length - 1].push(entry);
    else leading.push(entry);
  }
  if (!groups.length) return leading.length ? [build(1, leading, undefined, observations)] : [];
  const decisions = groups.map((g) => g.find((e): e is DecisionEntry => e.type === 'decision'));
  return groups.map((records, i) => build(i + 1, records, decisions[i + 1], observations));
}

export function currentStepNumber(steps: Step[]): number {
  const last = steps[steps.length - 1];
  return last?.decision ? last.number : 0;
}
