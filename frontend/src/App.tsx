import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, apiRequest, DEFAULT_LIMITS, isUncertain, parseReadiness, parseUsage, reconcileModel, runIdFromHash } from './console.ts';
import type { Limits, Readiness, Run, RunPage, TokenUsage } from './console.ts';
import { applyDefaultLimits, emptyForm, formFromRun } from './form.ts';
import type { CreateRunRequest, RunForm } from './form.ts';
import { createHealthMonitor } from './health.ts';
import type { HealthState } from './health.ts';
import { ReadinessPanel } from './components/ReadinessPanel.tsx';
import { NewRunForm } from './components/NewRunForm.tsx';
import { RunList } from './components/RunList.tsx';
import { RunView } from './components/RunView.tsx';
import { StatsView } from './components/StatsView.tsx';
import { statsFromHash } from './stats.ts';

export interface ReadinessState { readiness: Readiness | null; connected: boolean; checking: boolean; checkedAt: number | null }
export interface RunsState { runs: Run[]; error: string | null; loading: boolean; usage: TokenUsage | null }

export function App() {
  const [health, setHealth] = useState<HealthState>({ kind: 'checking' });
  const [ready, setReady] = useState<ReadinessState>({ readiness: null, connected: false, checking: true, checkedAt: null });
  const [runs, setRuns] = useState<RunsState>({ runs: [], error: null, loading: true, usage: null });
  const [selected, setSelected] = useState<string | null>(() => runIdFromHash(window.location.hash));
  const [showStats, setShowStats] = useState(() => statsFromHash(window.location.hash));
  const [form, setForm] = useState<RunForm>(() => emptyForm(DEFAULT_LIMITS));
  const [submitting, setSubmitting] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createUncertain, setCreateUncertain] = useState(false);
  const healthRefresh = useRef<() => Promise<void>>(async () => {});
  const defaults = useRef<Limits>(DEFAULT_LIMITS);
  const autoSelected = useRef(false);

  useEffect(() => {
    const monitor = createHealthMonitor(setHealth);
    healthRefresh.current = monitor.refresh;
    void monitor.refresh();
    return () => monitor.dispose();
  }, []);

  const loadReadiness = useCallback(async (signal?: AbortSignal) => {
    setReady((state) => ({ ...state, checking: true }));
    try {
      const readiness = parseReadiness(await apiRequest<unknown>('/readiness', { signal }));
      if (signal?.aborted) return;
      setForm((current) => ({ ...applyDefaultLimits(current, defaults.current, readiness.default_limits), model: reconcileModel(current.model, readiness) }));
      defaults.current = readiness.default_limits;
      setReady({ readiness, connected: true, checking: false, checkedAt: Date.now() });
      if (!autoSelected.current) {
        autoSelected.current = true;
        if (readiness.active_run_id && !runIdFromHash(window.location.hash)) select(readiness.active_run_id);
      }
    } catch {
      if (signal?.aborted) return;
      setReady((state) => ({ ...state, connected: false, checking: false, checkedAt: Date.now() }));
    }
  }, []);

  const loadRuns = useCallback(async (signal?: AbortSignal) => {
    setRuns((state) => ({ ...state, loading: true }));
    try {
      const [page, usage] = await Promise.all([
        apiRequest<RunPage>('/runs?limit=50&offset=0', { signal }),
        apiRequest<unknown>('/usage', { signal }).then(parseUsage, () => null),
      ]);
      if (signal?.aborted) return;
      if (!Array.isArray(page.runs)) throw new Error('Invalid run list');
      setRuns({ runs: page.runs, error: null, loading: false, usage });
    } catch {
      if (signal?.aborted) return;
      setRuns((state) => ({ ...state, error: 'Run history could not be loaded. Showing the last known list.', loading: false }));
    }
  }, []);

  // Configuration-only reads: no device or provider contact.
  useEffect(() => {
    const controller = new AbortController();
    void loadReadiness(controller.signal);
    void loadRuns(controller.signal);
    const timer = setInterval(() => { void loadReadiness(controller.signal); void loadRuns(controller.signal); }, 5000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [loadReadiness, loadRuns]);

  useEffect(() => {
    const onHash = () => { setSelected(runIdFromHash(window.location.hash)); setShowStats(statsFromHash(window.location.hash)); };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  function select(runId: string | null) {
    const hash = runId ? `#run=${runId}` : '';
    if (window.location.hash !== hash) history.pushState(null, '', hash || window.location.pathname);
    setSelected(runId);
    setShowStats(false);
  }

  function openStats() {
    if (window.location.hash !== '#stats') history.pushState(null, '', '#stats');
    setSelected(null);
    setShowStats(true);
  }

  const refreshAll = useCallback(() => {
    setCreateUncertain(false);
    setCreateError(null);
    void healthRefresh.current();
    void loadReadiness();
    void loadRuns();
  }, [loadReadiness, loadRuns]);

  async function create(request: CreateRunRequest) {
    if (submitting || createUncertain) return;
    setSubmitting(true);
    setCreateError(null);
    try {
      const run = await apiRequest<Run>('/runs', { method: 'POST', body: request });
      setForm((current) => ({ ...emptyForm(defaults.current), deviceId: current.deviceId, limits: current.limits }));
      select(run.run_id);
    } catch (error) {
      // A lost response may still have started a run: never resubmit automatically.
      if (isUncertain(error)) {
        setCreateUncertain(true);
        setCreateError('The service did not confirm whether the run started. Select “Refresh” and check the run list before trying again.');
      } else {
        setCreateError(error instanceof ApiError ? error.message : 'The run could not be started.');
      }
    } finally {
      setSubmitting(false);
      void loadReadiness();
      void loadRuns();
    }
  }

  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  /** Deletes stored runs; a lost response is reconciled by re-reading the list, never retried. */
  async function remove(runId: string | null) {
    if (deleting) return;
    const question = runId
      ? 'Delete this run with its screenshots and history? This cannot be undone.'
      : 'Delete all stored runs with their screenshots and history? An open run is kept. This cannot be undone.';
    if (!window.confirm(question)) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await apiRequest<unknown>(runId ? `/runs/${encodeURIComponent(runId)}` : '/runs', { method: 'DELETE' });
      if (runId === null ? selected !== null && selected !== ready.readiness?.active_run_id : selected === runId) select(null);
    } catch (error) {
      setDeleteError(isUncertain(error)
        ? 'The service did not confirm the deletion. Check the run list before trying again.'
        : error instanceof ApiError ? error.message : 'The run could not be deleted.');
    } finally {
      setDeleting(false);
      void loadReadiness();
      void loadRuns();
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="/" onClick={(event) => { event.preventDefault(); select(null); }} aria-label="Visto, new run">
          <span className="brand-mark" aria-hidden="true">A</span>
          Visto
        </a>
        <span className="topbar-actions">
          <button type="button" className="secondary small" onClick={openStats} aria-pressed={showStats}>Stats</button>
          <span className="topbar-note">Local console</span>
        </span>
      </header>
      <ReadinessPanel health={health} state={ready} onRefresh={refreshAll} onOpenRun={select} />
      <div className="layout">
        <RunList state={runs} selected={selected} activeRunId={ready.readiness?.active_run_id ?? null} deleting={deleting} deleteError={deleteError}
          onSelect={select} onNew={() => select(null)} onRefresh={() => void loadRuns()} onDelete={(runId) => void remove(runId)} onDeleteAll={() => void remove(null)} />
        <main className="workspace" id="main">
          {showStats
            ? <StatsView onOpenRun={select} />
            : selected
            ? <RunView key={selected} runId={selected} activeRunId={ready.readiness?.active_run_id ?? null} deleting={deleting}
                onChanged={() => { void loadReadiness(); void loadRuns(); }} onBack={() => select(null)} onDelete={() => void remove(selected)}
                onRerun={(run) => { setForm(formFromRun(run, ready.readiness?.models ?? [], defaults.current)); setCreateError(null); select(null); }} />
            : <NewRunForm form={form} onChange={setForm} readiness={ready.readiness} connected={ready.connected}
                submitting={submitting} uncertain={createUncertain} error={createError} onSubmit={create} onRefresh={refreshAll} />}
        </main>
      </div>
      <footer className="footer">Visto <span aria-hidden="true">/</span> Local service only. Screenshots and test text are visible to anyone with access to this computer’s service.</footer>
    </div>
  );
}

