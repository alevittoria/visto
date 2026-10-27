import type { ReactNode } from 'react';
import { formatTokens, parseUsage } from '../console.ts';
import type { Run } from '../console.ts';
import { cleanupWarning, formatDuration, formatTime } from '../history.ts';
import { parseRunCost, runCostText } from '../stats.ts';

/** Collapsed run configuration and usage; `children` adds extra content such as report links. */
export function RunDetails({ run, children }: { run: Run; children?: ReactNode }) {
  const observeOnly = Array.isArray(run.configuration?.capabilities) && run.configuration.capabilities.length === 0;
  const usage = parseUsage(run.usage);
  const cost = runCostText(parseRunCost(run.cost));
  const limits = run.configuration.limits;
  const warning = cleanupWarning(run);
  return (
    <details className="panel run-details">
      <summary>Details</summary>
      <dl className="facts compact">
        <div><dt>Device</dt><dd>{run.device_id}</dd></div>
        <div><dt>Mode</dt><dd>{observeOnly ? 'Observe only' : 'AI may operate the device'}</dd></div>
        <div><dt>AI model</dt><dd>{run.configuration?.identity?.model ?? 'unknown'}</dd></div>
        <div><dt>Started</dt><dd><time dateTime={run.created_at}>{formatTime(run.created_at)}</time></dd></div>
        <div><dt>Input tokens</dt><dd>{usage ? formatTokens(usage.input_tokens) : 'unknown'}</dd></div>
        <div><dt>Output tokens</dt><dd>{usage ? formatTokens(usage.output_tokens) : 'unknown'}</dd></div>
        <div><dt>Estimated cost</dt><dd title={cost.title}>{cost.text}</dd></div>
        <div><dt>Limits</dt><dd>{formatDuration(limits.wall_time_ms)}, {limits.max_actions} actions, {limits.max_inferences} AI steps</dd></div>
      </dl>
      {usage && usage.unknown_usage_decisions > 0 && (
        <p className="help">{usage.unknown_usage_decisions} AI steps did not report token usage and are not counted.</p>
      )}
      {(run.goal.expected_result || run.goal.constraints.length > 0) && (
        <div className="goal-extra">
          {run.goal.expected_result && <p><strong>Expected result:</strong> {run.goal.expected_result}</p>}
          {run.goal.constraints.length > 0 && <><strong>Constraints:</strong><ul>{run.goal.constraints.map((item, i) => <li key={i}>{item}</li>)}</ul></>}
        </div>
      )}
      {warning && <p className="blocked">{warning}</p>}
      {children}
    </details>
  );
}
