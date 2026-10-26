import type { HealthState } from '../health.ts';
import type { ReadinessState } from '../App.tsx';

interface Props {
  health: HealthState;
  state: ReadinessState;
  onRefresh: () => void;
  onOpenRun: (runId: string) => void;
  onOpenSettings: () => void;
}

export function ReadinessPanel({ health, state, onRefresh, onOpenRun, onOpenSettings }: Props) {
  const { readiness, connected } = state;
  const tone = !connected ? 'disconnected' : readiness?.configured ? 'connected' : 'warning';
  const title = !connected
    ? (state.checkedAt === null ? 'Connecting to the local service…' : 'Local service unreachable')
    : !readiness?.configured ? 'Setup needed'
      : readiness.active_run_id ? 'A run is open'
        : readiness.execution_available ? 'Ready to start a run' : 'Not accepting new runs';
  return (
    <section className="readiness" aria-labelledby="readiness-title">
      <div className="readiness-head">
        <span className={`indicator ${tone}`} aria-hidden="true" />
        <div role="status" aria-live="polite" aria-atomic="true">
          <h2 id="readiness-title">{title}</h2>
          {!connected && state.checkedAt !== null && (
            <p className="muted">The console cannot reach the local service. Stored runs and controls are unavailable until it responds. Start the backend, then select Refresh.</p>
          )}
          {connected && readiness?.configuration_error && <p className="error-text">{readiness.configuration_error}</p>}
          {connected && readiness && readiness.cleanup_attention_run_ids.length > 0 && (
            <div className="blocked">
              Device cleanup did not finish for {readiness.cleanup_attention_run_ids.length === 1 ? 'a previous run' : `${readiness.cleanup_attention_run_ids.length} previous runs`}.
              Check the device and its automation session before starting a run on the same device. Recorded results are unchanged.
              {readiness.cleanup_attention_run_ids.map((id) => (
                <button key={id} type="button" className="link" onClick={() => onOpenRun(id)}>View run {id.slice(0, 8)}</button>
              ))}
            </div>
          )}
        </div>
        <button type="button" className="secondary" onClick={onRefresh} disabled={state.checking && state.checkedAt === null}>Refresh</button>
      </div>
      {connected && readiness && (
        <dl className="facts">
          <div><dt>AI provider key</dt><dd>{readiness.provider_key_configured
            ? 'Configured'
            : <>Missing<button type="button" className="link" onClick={onOpenSettings}>Open settings</button></>}</dd></div>
          <div><dt>AI model</dt><dd>{readiness.model ?? 'Not set'}</dd></div>
          <div><dt>Device automation service</dt><dd>{readiness.appium_url ?? 'Not set'}</dd></div>
          <div>
            <dt>Open run</dt>
            <dd>{readiness.active_run_id
              ? <button type="button" className="link" onClick={() => onOpenRun(readiness.active_run_id as string)}>View open run</button>
              : 'None'}</dd>
          </div>
          <div><dt>Service</dt><dd>{health.kind === 'connected' ? `Version ${health.health.version}` : health.kind === 'checking' ? 'Checking…' : 'Not responding'}</dd></div>
        </dl>
      )}
      {connected && <p className="fine-print">This check reads server settings only. It does not contact the device or the AI provider; device connectivity is checked when a run starts.</p>}
    </section>
  );
}
