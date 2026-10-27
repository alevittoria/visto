import { useCallback, useEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { apiRequest, deviceLabel, emptyDeviceHint, parseDevices } from '../console.ts';
import type { AttachedDevice, DeviceInventory, Platform } from '../console.ts';
import { nextDevicePoll } from '../start.ts';

interface Props {
  value: string;
  /** An explicit choice by the operator in the device menu. */
  onSelect: (serial: string, devices: AttachedDevice[]) => void;
  /** Every completed listing, so the caller can reconcile its choice. */
  onLoaded: (devices: AttachedDevice[]) => void;
  invalid: boolean;
  /** Platforms the server lists devices for (readiness). */
  platforms: Platform[];
  /** False while readiness is unknown, the service is unreachable or a run is open: listing may reconnect devices, so it never polls then. */
  pollingAllowed: boolean;
  /** Ids of messages describing the chip, such as a validation error. */
  describedBy?: string;
}

type State = { loading: boolean; inventory: DeviceInventory | null; error: string | null };

const pageVisible = () => document.visibilityState === 'visible';

/** Device picker for the start screen: a chip that opens a small device menu. */
export function DeviceChip({ value, onSelect, onLoaded, invalid, platforms, pollingAllowed, describedBy }: Props) {
  // Nothing is listed automatically while a run is open, so the first state is idle then.
  const [state, setState] = useState<State>({ loading: pollingAllowed, inventory: null, error: null });
  const [open, setOpen] = useState(false);
  const active = useRef<AbortController | null>(null);
  const loaded = useRef(onLoaded);
  loaded.current = onLoaded;
  const wrap = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);

  // Listing runs `adb devices` and the iOS listers on the server. A new request aborts the previous one.
  const load = useCallback(async () => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setState((current) => ({ ...current, loading: true, error: null }));
    try {
      const inventory = parseDevices(await apiRequest<unknown>('/devices', { signal: controller.signal }));
      if (controller.signal.aborted) return;
      setState({ loading: false, inventory, error: inventory.available ? null : inventory.error ?? 'Devices could not be listed.' });
      loaded.current(inventory.devices);
    } catch (error) {
      if (controller.signal.aborted) return;
      setState({ loading: false, inventory: null, error: error instanceof Error ? error.message : 'Devices could not be listed.' });
      loaded.current([]);
    } finally {
      if (active.current === controller) active.current = null;
    }
  }, []);

  /** Automatic triggers never interrupt a listing already in flight. */
  const loadIfIdle = useCallback(() => {
    if (active.current === null) void load();
  }, [load]);

  useEffect(() => () => {
    active.current?.abort();
    active.current = null;
  }, []);

  // Automatic listing (on mount, when a run closes, on returning to the tab) only while no run is open:
  // listing may try to reconnect devices. Menu open and Refresh stay available.
  useEffect(() => {
    if (pollingAllowed) loadIfIdle();
  }, [pollingAllowed, loadIfIdle]);

  // Coming back to the tab re-lists, so a phone connected meanwhile shows up.
  useEffect(() => {
    if (!pollingAllowed) return;
    const onReturn = () => { if (pageVisible()) loadIfIdle(); };
    document.addEventListener('visibilitychange', onReturn);
    window.addEventListener('focus', onReturn);
    return () => {
      document.removeEventListener('visibilitychange', onReturn);
      window.removeEventListener('focus', onReturn);
    };
  }, [pollingAllowed, loadIfIdle]);

  const devices = state.inventory?.devices ?? [];
  const selectable = devices.filter((device) => device.selectable);
  const polling = nextDevicePoll({ selectableCount: selectable.length, runOpen: !pollingAllowed, pageVisible: pageVisible() });

  // Bounded re-listing while nothing is selectable; a failed list counts as nothing selectable.
  useEffect(() => {
    if (state.loading || polling === null) return;
    const timer = setTimeout(() => { if (pageVisible()) loadIfIdle(); }, polling);
    return () => clearTimeout(timer);
  }, [state, polling, loadIfIdle]);

  // Close on a click outside the chip and its menu.
  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (wrap.current && !wrap.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [open]);

  // Move focus into the menu when it opens: the chosen device, else the first ready one, else Refresh.
  useEffect(() => {
    if (!open || !menu.current) return;
    const target = menu.current.querySelector<HTMLButtonElement>('button[aria-pressed=true]')
      ?? menu.current.querySelector<HTMLButtonElement>('button:not(:disabled):not([aria-disabled=true])');
    target?.focus();
  }, [open]);

  function toggle() {
    if (!open) loadIfIdle();
    setOpen(!open);
  }

  function close() {
    setOpen(false);
    trigger.current?.focus();
  }

  function choose(serial: string) {
    onSelect(serial, devices);
    close();
  }

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === 'Escape' && open) {
      event.stopPropagation();
      close();
    }
  }

  const current = selectable.find((device) => device.serial === value) ?? null;
  const chipText = current ? deviceLabel(current)
    : state.loading && !state.inventory ? 'Looking for devices…'
    : !state.inventory && !state.error ? 'Not listed yet'
    : selectable.length > 0 ? 'Choose a device' : 'No device ready';
  const status = state.error ?? (!state.inventory && !state.loading
    ? 'Devices are listed automatically only while the service is ready and no run is open. Press Refresh to list them now.'
    : devices.length === 0 && !state.loading
    ? emptyDeviceHint(platforms)
    : `${selectable.length} ready of ${devices.length} connected.`);

  return (
    <div className="chip-wrap" ref={wrap} onKeyDown={onKeyDown}
      onBlur={(event) => { if (open && !event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false); }}>
      <button type="button" id="device" ref={trigger} className={`chip${invalid ? ' invalid' : ''}`} onClick={toggle}
        aria-expanded={open} aria-controls={open ? 'device-menu' : undefined} aria-describedby={describedBy}
        title={current ? chipText : undefined}>
        <span className={`chip-dot${current ? ' ready' : ''}`} aria-hidden="true" />
        <span className="chip-key">Device</span>
        <span className="chip-value">{chipText}</span>
      </button>
      {open && (
        <div className="popover" id="device-menu" ref={menu} role="group" aria-label="Devices" tabIndex={-1}>
          {devices.length > 0 && (
            <ul className="device-options">
              {devices.map((device) => (
                <li key={device.serial}>
                  {/* Not-ready devices stay focusable so keyboard and screen reader users can read why. */}
                  <button type="button" className="device-option" aria-disabled={device.selectable ? undefined : true}
                    aria-pressed={device.selectable && device.serial === value}
                    onClick={() => { if (device.selectable) choose(device.serial); }}>
                    <span className={`chip-dot${device.selectable ? ' ready' : ''}`} aria-hidden="true" />
                    <span>{deviceLabel(device)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className={state.error ? 'error-text small-text' : 'help'} role="status" aria-live="polite">
            {status}
            {polling !== null && !state.loading ? ' Checking again automatically.' : ''}
          </p>
          {state.inventory?.notes.map((note) => <p key={note} className="help">{note}</p>)}
          <div className="popover-foot">
            {/* Stays enabled while listing so focus is not lost; a new request replaces the running one. */}
            <button type="button" className="secondary small" onClick={() => void load()} aria-busy={state.loading}>
              {state.loading ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
