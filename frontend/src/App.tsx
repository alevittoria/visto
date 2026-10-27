import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, apiRequest, DEFAULT_LIMITS, isUncertain, parseDevices, parseReadiness, reconcileModel, runIdFromHash } from './console.ts';
import type { AttachedDevice, Limits, Readiness, Run, RunPage } from './console.ts';
import { applyDefaultLimits, emptyForm, formFromRun } from './form.ts';
import type { CreateRunRequest, RunForm } from './form.ts';
import { createHealthMonitor } from './health.ts';
import type { HealthState } from './health.ts';
import { RunList } from './components/RunList.tsx';
import { RunView } from './components/RunView.tsx';
import { SettingsView } from './components/SettingsView.tsx';
import { StartScreen } from './components/StartScreen.tsx';
import { StatsView } from './components/StatsView.tsx';
import { settingsFromHash } from './settings.ts';
import { rerunPlan, rerunServiceBlock } from './start.ts';
import { statsFromHash } from './stats.ts';

export interface ReadinessState { readiness: Readiness | null; connected: boolean; checking: boolean; checkedAt: number | null }
export interface RunsState { runs: Run[]; error: string | null; loading: boolean }

const SIDEBAR_KEY = 'visto.sidebar';
const NARROW_QUERY = '(max-width: 960px)';
const FOCUSABLE = 'button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])';

function readSidebarCollapsed(): boolean {
  try { return window.localStorage.getItem(SIDEBAR_KEY) === 'collapsed'; } catch { return false; }
}

function storeSidebarCollapsed(collapsed: boolean) {
  try { window.localStorage.setItem(SIDEBAR_KEY, collapsed ? 'collapsed' : 'expanded'); } catch { /* a per-viewer convenience only */ }
}

function matchesNarrow(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia(NARROW_QUERY).matches;
}

type SubmitResult = { started: true } | { started: false; uncertain: boolean; error: string };

export function App() {
  const [health, setHealth] = useState<HealthState>({ kind: 'checking' });
  const [ready, setReady] = useState<ReadinessState>({ readiness: null, connected: false, checking: true, checkedAt: null });
  const [runs, setRuns] = useState<RunsState>({ runs: [], error: null, loading: true });
  const [selected, setSelected] = useState<string | null>(() => runIdFromHash(window.location.hash));
  const [showStats, setShowStats] = useState(() => statsFromHash(window.location.hash));
  const [showSettings, setShowSettings] = useState(() => settingsFromHash(window.location.hash));
  const [form, setForm] = useState<RunForm>(() => emptyForm(DEFAULT_LIMITS));
  const [submitting, setSubmitting] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createUncertain, setCreateUncertain] = useState(false);
  const [rerunBlocked, setRerunBlocked] = useState<{ runId: string; reason: string } | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsed);
  const [narrow, setNarrow] = useState(matchesNarrow);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // State can be stale between two fast clicks; this ref is the submit lock.
  const submittingRef = useRef(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
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
        if (!readiness.provider_key_configured && !window.location.hash) openSettings();
        else if (readiness.active_run_id && !runIdFromHash(window.location.hash)) select(readiness.active_run_id);
      }
    } catch {
      if (signal?.aborted) return;
      setReady((state) => ({ ...state, connected: false, checking: false, checkedAt: Date.now() }));
    }
  }, []);

  const loadRuns = useCallback(async (signal?: AbortSignal) => {
    setRuns((state) => ({ ...state, loading: true }));
    try {
      const page = await apiRequest<RunPage>('/runs?limit=50&offset=0', { signal });
      if (signal?.aborted) return;
      if (!Array.isArray(page.runs)) throw new Error('Invalid run list');
      setRuns({ runs: page.runs, error: null, loading: false });
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
    const onHash = () => { setSelected(runIdFromHash(window.location.hash)); setShowStats(statsFromHash(window.location.hash)); setShowSettings(settingsFromHash(window.location.hash)); };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  // A blocked rerun reason belongs to the run it was shown for.
  useEffect(() => { setRerunBlocked(null); }, [selected]);

  // Below 960 px the history is an overlay drawer, closed by default.
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia(NARROW_QUERY);
    const onChange = () => { setNarrow(query.matches); if (!query.matches) setDrawerOpen(false); };
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  // Open drawer: focus moves in, Tab stays inside, Escape closes, focus returns to the toggle.
  useEffect(() => {
    if (!drawerOpen) return;
    const panel = drawerRef.current;
    if (!panel) return;
    const focusables = () => Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
    focusables()[0]?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setDrawerOpen(false); return; }
      if (event.key !== 'Tab') return;
      const items = focusables();
      if (items.length === 0) { event.preventDefault(); return; }
      const first = items[0];
      const last = items[items.length - 1];
      const inside = panel.contains(document.activeElement);
      if (event.shiftKey && (!inside || document.activeElement === first)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (!inside || document.activeElement === last)) { event.preventDefault(); first.focus(); }
    };
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = overflow;
      // Runs after the drawer is gone and the page is no longer inert.
      const active = document.activeElement;
      if (!active || active === document.body || !active.isConnected) toggleRef.current?.focus();
    };
  }, [drawerOpen]);

  function toggleSidebar() {
    if (narrow) { setDrawerOpen((open) => !open); return; }
    const collapsed = !sidebarCollapsed;
    storeSidebarCollapsed(collapsed);
    setSidebarCollapsed(collapsed);
  }

  function select(runId: string | null) {
    const hash = runId ? `#run=${runId}` : '';
    if (window.location.hash !== hash) history.pushState(null, '', hash || window.location.pathname);
    setSelected(runId);
    setShowStats(false);
    setShowSettings(false);
  }

  function selectFromHistory(runId: string | null) {
    select(runId);
    setDrawerOpen(false);
  }

  function openStats() {
    if (window.location.hash !== '#stats') history.pushState(null, '', '#stats');
    setSelected(null);
    setShowStats(true);
    setShowSettings(false);
  }

  function openSettings() {
    if (window.location.hash !== '#settings') history.pushState(null, '', '#settings');
    setSelected(null);
    setShowStats(false);
    setShowSettings(true);
  }

  const refreshAll = useCallback(() => {
    setCreateUncertain(false);
    setCreateError(null);
    void healthRefresh.current();
    void loadReadiness();
    void loadRuns();
  }, [loadReadiness, loadRuns]);

  function lockSubmit(): boolean {
    if (submittingRef.current) return false;
    submittingRef.current = true;
    setSubmitting(true);
    return true;
  }

  function unlockSubmit() {
    submittingRef.current = false;
    setSubmitting(false);
  }

  /** Posts one new run and opens it; never resubmits. The caller holds the submit lock. */
  async function submitRun(request: CreateRunRequest): Promise<SubmitResult> {
    try {
      const run = await apiRequest<Run>('/runs', { method: 'POST', body: request });
      select(run.run_id);
      return { started: true };
    } catch (error) {
      // A lost response may still have started a run: never resubmit automatically.
      if (isUncertain(error)) {
        setCreateUncertain(true);
        return { started: false, uncertain: true, error: 'The service did not confirm whether the run started. Select “Refresh” and check the run list before trying again.' };
      }
      return { started: false, uncertain: false, error: error instanceof ApiError ? error.message : 'The run could not be started.' };
    } finally {
      void loadReadiness();
      void loadRuns();
    }
  }

  async function create(request: CreateRunRequest) {
    if (createUncertain || !lockSubmit()) return;
    setCreateError(null);
    try {
      const result = await submitRun(request);
      // Only a confirmed start from the start screen clears its draft; device and limits stay.
      if (result.started) setForm((current) => ({ ...emptyForm(defaults.current), deviceId: current.deviceId, platform: current.platform, limits: current.limits }));
      else setCreateError(result.error);
    } finally {
      unlockSubmit();
    }
  }

  /** One click: one device listing, then the same settings on the same device, or the reason it cannot start. */
  async function rerun(run: Run) {
    if (!lockSubmit()) return;
    setRerunBlocked(null);
    const block = (reason: string) => setRerunBlocked({ runId: run.run_id, reason });
    try {
      if (createUncertain) {
        block('An earlier start was not confirmed, so no run was started. Check the run history, then open New run and select Refresh.');
        return;
      }
      // Listing devices may reconnect phones: skip it when the service cannot start a run anyway.
      const serviceReason = rerunServiceBlock(ready.readiness, ready.connected);
      if (serviceReason !== null) { block(serviceReason); return; }
      let devices: AttachedDevice[];
      try {
        devices = parseDevices(await apiRequest<unknown>('/devices')).devices;
      } catch {
        block('The device list could not be read, so no run was started. Try again or use Edit and rerun.');
        return;
      }
      const plan = rerunPlan(run, devices, ready.readiness, ready.connected, defaults.current);
      if (plan.kind === 'blocked') { block(plan.reason); return; }
      setCreateError(null);
      const result = await submitRun(plan.request);
      // The run view has no Refresh button: point to the start screen's Refresh instead,
      // and explain there why Start is unavailable until then.
      if (!result.started && result.uncertain) setCreateError(result.error);
      if (!result.started) block(result.uncertain
        ? 'The service did not confirm whether the run started. Check the run history, then open New run and select Refresh before trying again.'
        : result.error);
    } finally {
      unlockSubmit();
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

  /** Back to the start screen with this run's settings prefilled. */
  function editRerun(run: Run) {
    setForm(formFromRun(run, ready.readiness?.models ?? [], defaults.current));
    setCreateError(null);
    select(null);
  }

  const sidebarShown = narrow ? drawerOpen : !sidebarCollapsed;
  const drawer = narrow && drawerOpen;
  const toggleLabel = narrow ? 'Open run history' : sidebarCollapsed ? 'Show run history' : 'Hide run history';

  return (
    <div className="app">
      <header className="topbar" inert={drawer}>
        <span className="topbar-start">
          <button type="button" ref={toggleRef} className="secondary icon-button" onClick={toggleSidebar}
            aria-label={toggleLabel} title={toggleLabel} aria-expanded={sidebarShown} aria-controls={sidebarShown ? 'run-history' : undefined}>
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
              <rect x="2" y="3" width="14" height="12" rx="2.5" />
              <path d="M7 3v12" />
            </svg>
          </button>
          <a className="brand" href="/" onClick={(event) => { event.preventDefault(); select(null); }} aria-label="Visto, new run">
            <span className="brand-mark" aria-hidden="true">V</span>
            Visto
          </a>
        </span>
        <span className="topbar-actions">
          <button type="button" className="secondary small" onClick={openStats} aria-pressed={showStats}>Stats</button>
          <button type="button" className="secondary small" onClick={openSettings} aria-pressed={showSettings}>Settings</button>
          <span className="topbar-note">Local console</span>
        </span>
      </header>
      <div className={`layout${sidebarShown && !narrow ? ' with-sidebar' : ''}`}>
        {sidebarShown && (
          <aside id="run-history" ref={drawerRef} className={`sidebar${drawer ? ' drawer' : ''}`}
            role={drawer ? 'dialog' : undefined} aria-modal={drawer ? true : undefined} aria-label={drawer ? 'Run history' : undefined}>
            <RunList state={runs} selected={selected} activeRunId={ready.readiness?.active_run_id ?? null} deleting={deleting} deleteError={deleteError}
              onSelect={selectFromHistory} onNew={() => selectFromHistory(null)} onRefresh={() => void loadRuns()}
              onDelete={(runId) => void remove(runId)} onDeleteAll={() => void remove(null)}
              onClose={drawer ? () => setDrawerOpen(false) : undefined} />
          </aside>
        )}
        {drawer && <div className="drawer-backdrop" aria-hidden="true" onClick={() => setDrawerOpen(false)} />}
        <main className="workspace" id="main" inert={drawer}>
          {showSettings
            ? <SettingsView health={health} readiness={ready.readiness} connected={ready.connected} onChanged={() => void loadReadiness()} />
            : showStats
            ? <StatsView onOpenRun={select} />
            : selected
            ? <RunView key={selected} runId={selected} activeRunId={ready.readiness?.active_run_id ?? null} deleting={deleting}
                onChanged={() => { void loadReadiness(); void loadRuns(); }} onBack={() => select(null)} onDelete={() => void remove(selected)}
                onEditRerun={editRerun} onRerun={rerun} rerunBlockedReason={rerunBlocked?.runId === selected ? rerunBlocked.reason : null} />
            : <StartScreen form={form} onChange={setForm} readiness={ready.readiness} connected={ready.connected} checked={ready.checkedAt !== null}
                submitting={submitting} uncertain={createUncertain} error={createError} onSubmit={create} onRefresh={refreshAll}
                onOpenSettings={openSettings} onOpenRun={select} />}
        </main>
      </div>
      <footer className="footer" inert={drawer}>Visto <span aria-hidden="true">/</span> Local service only. Screenshots and test text are visible to anyone with access to this computer’s service.</footer>
    </div>
  );
}
