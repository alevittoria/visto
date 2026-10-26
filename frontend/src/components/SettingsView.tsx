import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError, isUncertain } from '../console.ts';
import { deleteKey, loadSettings, saveSettings, setKey, settingsBody, verifyKey, verifyMessage } from '../settings.ts';
import type { IosSettings, SettingsView as Settings, VerifyResult } from '../settings.ts';

interface Props { onChanged: () => void }

type Message = { text: string; tone: 'error' | 'info' };

const IOS_FIELDS: { name: 'team_id' | 'signing_id' | 'wda_bundle_id' | 'wda_derived_data'; label: string; help: string }[] = [
  { name: 'team_id', label: 'Development team ID', help: 'Signs the WebDriverAgent runner for a physical iPhone.' },
  { name: 'signing_id', label: 'Signing identity', help: 'Leave empty to use the automatic identity, or set the certificate type, usually "Apple Development", not the full name. Run security find-identity -v -p codesigning in a terminal to see what you have.' },
  { name: 'wda_bundle_id', label: 'WebDriverAgent bundle ID', help: 'A bundle ID unique to your team.' },
  { name: 'wda_derived_data', label: 'Derived data folder', help: 'Where the built runner is kept. Leave empty for the default.' },
];

const errorText = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);
const UNCONFIRMED = 'The service did not confirm the change. The values shown were re-read from the service.';

function MessageLine({ message }: { message: Message | null }) {
  if (!message) return null;
  return message.tone === 'error'
    ? <p className="error-text" role="alert">{message.text}</p>
    : <p className="info-text" role="status">{message.text}</p>;
}

export function SettingsView({ onChanged }: Props) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [priceRefresh, setPriceRefresh] = useState(true);
  const [ios, setIos] = useState<IosSettings | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [keyMessage, setKeyMessage] = useState<Message | null>(null);
  const [saveMessage, setSaveMessage] = useState<Message | null>(null);

  const adopt = useCallback((value: Settings) => {
    setSettings(value);
    setPriceRefresh(value.price_refresh);
    setIos(value.ios);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadSettings(controller.signal).then(
      (value) => { if (!controller.signal.aborted) { adopt(value); setLoadError(null); } },
      (error) => { if (!controller.signal.aborted) setLoadError(errorText(error, 'Settings could not be loaded.')); },
    );
    return () => controller.abort();
  }, [adopt]);

  /** Re-reads stored settings after an unconfirmed write so the page shows what was really saved. */
  async function reconcile() {
    try { adopt(await loadSettings()); } catch { /* keep the last known values */ }
  }

  async function keyAction(action: () => Promise<void>, failure: string) {
    if (busy) return;
    setBusy(true);
    setKeyMessage(null);
    try { await action(); }
    catch (error) {
      const uncertain = isUncertain(error);
      setKeyMessage({ tone: 'error', text: uncertain ? UNCONFIRMED : errorText(error, failure) });
      if (uncertain) await reconcile();
    } finally { setBusy(false); onChanged(); }
  }

  function submitKey(event: FormEvent) {
    event.preventDefault();
    const value = apiKey.trim();
    if (!value) return;
    setApiKey('');
    void keyAction(async () => {
      const key = await setKey(value);
      setSettings((current) => (current ? { ...current, key } : current));
      setKeyMessage({ tone: 'info', text: 'Key saved.' });
    }, 'The key could not be saved.');
  }

  function removeKey() {
    if (!window.confirm('Remove the stored provider key? Runs cannot start until a key is saved again.')) return;
    void keyAction(async () => {
      const key = await deleteKey();
      setSettings((current) => (current ? { ...current, key } : current));
      setKeyMessage({ tone: 'info', text: 'Key removed.' });
    }, 'The key could not be removed.');
  }

  function verify() {
    void keyAction(async () => {
      const result: VerifyResult = await verifyKey();
      setKeyMessage({ tone: result === 'ok' ? 'info' : 'error', text: verifyMessage(result) });
    }, 'The key could not be checked.');
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy || !settings) return;
    setBusy(true);
    setSaveMessage(null);
    try {
      adopt(await saveSettings(settingsBody(settings, priceRefresh, ios)));
      setSaveMessage({ tone: 'info', text: 'Settings saved.' });
    } catch (error) {
      const uncertain = isUncertain(error);
      setSaveMessage({ tone: 'error', text: uncertain ? UNCONFIRMED : errorText(error, 'Settings could not be saved.') });
      if (uncertain) await reconcile();
    } finally { setBusy(false); onChanged(); }
  }

  if (!settings) {
    return (
      <section className="panel" aria-labelledby="settings-title">
        <h1 id="settings-title">Settings</h1>
        {loadError ? <p className="error-text" role="alert">{loadError}</p> : <p className="muted" role="status">Loading settings…</p>}
      </section>
    );
  }

  const { key } = settings;
  return (
    <section aria-labelledby="settings-title">
      <div className="panel">
        <h1 id="settings-title">Settings</h1>
        <h2>AI provider key</h2>
        <p role="status">{key.configured ? `Configured, ending in ••••${key.last4 ?? ''}` : 'Not configured'}</p>
        <form onSubmit={submitKey} autoComplete="off">
          <div className="field">
            <label htmlFor="provider-key">{key.configured ? 'Replace key' : 'Provider API key'}</label>
            <input id="provider-key" type="password" autoComplete="off" spellCheck={false} value={apiKey}
              onChange={(event) => setApiKey(event.target.value)} disabled={busy} />
            <p className="help">The key is never shown again after saving. It is stored in plain text in the Visto folder in your user profile; anyone who can read that folder can read it.</p>
          </div>
          <div className="settings-actions">
            <button type="submit" disabled={busy || !apiKey.trim()}>Save key</button>
            <button type="button" className="secondary" onClick={verify} disabled={busy || !key.configured}>Verify</button>
            <button type="button" className="danger" onClick={removeKey} disabled={busy || !key.configured}>Remove</button>
          </div>
        </form>
        <MessageLine message={keyMessage} />
        <p className="fine-print">Verify reads the default model's metadata with the stored key. It does not run a model request.</p>
      </div>

      <form className="panel" onSubmit={(event) => void save(event)}>
        <h2>Preferences</h2>
        <div className="field">
          <label className="check-row"><input type="checkbox" checked={priceRefresh} disabled={busy}
            onChange={(event) => setPriceRefresh(event.target.checked)} /> Refresh model prices daily</label>
          <p className="help">Cost estimates use a public price list that is downloaded once a day. Turn this off to keep the last stored list.</p>
        </div>
        {settings.ios_supported && ios !== null && (
          <>
            <h2>iOS signing</h2>
            {settings.wda_rebuild_needed && (
              <div className="blocked" role="status">The installed automation driver changed since these values were saved. Rebuild WebDriverAgent, then save the iOS values again to clear this notice.</div>
            )}
            {IOS_FIELDS.map((item) => (
              <div className="field" key={item.name}>
                <label htmlFor={`ios-${item.name}`}>{item.label} <span className="optional">(optional)</span></label>
                <input id={`ios-${item.name}`} type="text" autoComplete="off" spellCheck={false} value={ios[item.name]} disabled={busy}
                  onChange={(event) => setIos({ ...ios, [item.name]: event.target.value })} />
                <p className="help">{item.help}</p>
              </div>
            ))}
            <div className="field">
              <label className="check-row"><input type="checkbox" checked={ios.prebuilt_wda} disabled={busy}
                onChange={(event) => setIos({ ...ios, prebuilt_wda: event.target.checked })} /> Use a prebuilt WebDriverAgent</label>
            </div>
            <div className="field">
              <span className="field-label">WebDriverAgent project</span>
              <p className="path-text">{settings.wda_project ?? 'Not found'}</p>
            </div>
          </>
        )}
        <div className="settings-actions">
          <button type="submit" disabled={busy}>Save settings</button>
        </div>
        <MessageLine message={saveMessage} />
      </form>
    </section>
  );
}
