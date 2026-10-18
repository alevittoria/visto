import { useEffect, useRef, useState } from 'react';
import { canDictate, MAX_RECORDING_MS, pickRecordingType, transcribe } from '../speech.ts';

interface Props {
  /** Visible field name, used in the accessible label ("Dictate goal"). */
  field: string;
  disabled: boolean;
  onText: (text: string) => void;
}

type Phase = 'idle' | 'starting' | 'recording' | 'transcribing';

/** Records one utterance with the microphone and hands back the server transcript. */
export function DictateButton({ field, disabled, onText }: Props) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const recorder = useRef<MediaRecorder | null>(null);

  // Leaving the form discards an unfinished recording and releases the microphone.
  useEffect(() => () => {
    const media = recorder.current;
    if (media?.state !== 'recording') return;
    media.onstop = () => media.stream.getTracks().forEach((track) => track.stop());
    media.stop();
  }, []);

  useEffect(() => {
    if (phase !== 'recording') return;
    const started = Date.now();
    const timer = setInterval(() => {
      const ms = Date.now() - started;
      setElapsed(Math.floor(ms / 1000));
      if (ms >= MAX_RECORDING_MS && recorder.current?.state === 'recording') recorder.current.stop();
    }, 250);
    return () => clearInterval(timer);
  }, [phase]);

  const env = typeof window === 'undefined' ? {} : { isSecureContext: window.isSecureContext, mediaDevices: navigator.mediaDevices, MediaRecorder: window.MediaRecorder };
  const type = canDictate(env) ? pickRecordingType((t) => MediaRecorder.isTypeSupported(t)) : null;
  if (type === null) return null;

  async function start() {
    setError(null);
    setPhase('starting');
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError('Microphone access was denied or is unavailable.');
      setPhase('idle');
      return;
    }
    const chunks: Blob[] = [];
    const media = new MediaRecorder(stream, { mimeType: type! });
    media.ondataavailable = (event) => { if (event.data.size > 0) chunks.push(event.data); };
    media.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop());
      recorder.current = null;
      const recording = new Blob(chunks, { type: type!.split(';')[0] });
      if (recording.size === 0) { setError('Nothing was recorded.'); setPhase('idle'); return; }
      setPhase('transcribing');
      try {
        const result = await transcribe(recording);
        if (result.text.trim()) onText(result.text);
        else setError('No speech was recognised.');
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Transcription failed.');
      } finally {
        setPhase('idle');
      }
    };
    recorder.current = media;
    setElapsed(0);
    media.start();
    setPhase('recording');
  }

  const recording = phase === 'recording';
  const busy = phase === 'starting' || phase === 'transcribing';
  return (
    <span className="dictate">
      <button type="button" className={`secondary small${recording ? ' recording' : ''}`}
        disabled={(disabled && !recording) || busy} aria-pressed={recording}
        aria-label={recording ? `Stop dictating ${field}` : `Dictate ${field}`}
        onClick={() => (recording ? recorder.current?.stop() : void start())}>
        {recording ? `■ Stop (${elapsed}s)` : phase === 'transcribing' ? 'Transcribing…' : '🎤 Dictate'}
      </button>
      <span aria-live="polite" className="help">
        {recording ? 'Listening… press Stop when done; the text appears after transcription.' : phase === 'transcribing' ? 'Transcribing your recording…' : ''}
      </span>
      {error && <span className="error-text small-text" role="alert">{error}</span>}
    </span>
  );
}
