import { useCallback, useEffect, useRef, useState } from 'react';
import { apiRequest, deviceLabel, parseDevices } from '../console.ts';
import type { AttachedDevice, DeviceInventory } from '../console.ts';

interface Props {
  value: string;
  onSelect: (serial: string, devices: AttachedDevice[]) => void;
  onLoaded: (devices: AttachedDevice[]) => void;
  invalid: boolean;
  describedBy?: string;
}

type State = { loading: boolean; inventory: DeviceInventory | null; error: string | null };

export function DeviceSelect({ value, onSelect, onLoaded, invalid, describedBy }: Props) {
  const [state, setState] = useState<State>({ loading: true, inventory: null, error: null });
  const active = useRef<AbortController | null>(null);
  const loaded = useRef(onLoaded);
  loaded.current = onLoaded;

  // Listing runs `adb devices` and the iOS listers on the server: only on open and on explicit refresh.
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
    }
  }, []);

  useEffect(() => {
    void load();
    return () => active.current?.abort();
  }, [load]);

  const devices = state.inventory?.devices ?? [];
  const selectable = devices.filter((device) => device.selectable);
  const placeholder = state.loading && !state.inventory ? 'Looking for devices…'
    : selectable.length ? 'Select a device' : 'No ready device found';

  return (
    <>
      <div className="inline">
        <select id="device" value={selectable.some((d) => d.serial === value) ? value : ''} onChange={(e) => onSelect(e.target.value, devices)}
          aria-invalid={invalid} aria-describedby={describedBy} aria-busy={state.loading}>
          <option value="" disabled>{placeholder}</option>
          {devices.map((device) => (
            <option key={device.serial} value={device.serial} disabled={!device.selectable}>{deviceLabel(device)}</option>
          ))}
        </select>
        <button type="button" className="secondary" onClick={() => void load()} disabled={state.loading}>
          {state.loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      <p id="device-status" className={state.error ? 'error-text' : 'help'} aria-live="polite">
        {state.error ?? (devices.length === 0 && !state.loading
          ? 'Connect an Android phone with USB debugging enabled, or boot an iOS simulator from Xcode, then press Refresh.'
          : `${selectable.length} ready of ${devices.length} connected.`)}
      </p>
      {state.inventory?.notes.map((note) => <p key={note} className="help">{note}</p>)}
    </>
  );
}
