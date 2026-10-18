import { useState } from 'react';
import type { FormEvent } from 'react';
import type { ControlAvailability, Run } from '../console.ts';
import { formatTime } from '../history.ts';

export type ControlOperation = 'pause' | 'resume' | 'cancel';
export interface Message { tone: 'info' | 'error'; text: string }

interface Props {
  run: Run;
  available: ControlAvailability;
  busy: boolean;
  uncertain: boolean;
  message: Message | null;
  onControl: (operation: ControlOperation) => void;
  onAnswer: (questionId: string, text: string) => Promise<void>;
  onReconnect: () => void;
}

export function RunControls({ run, available, busy, uncertain, message, onControl, onAnswer, onReconnect }: Props) {
  const [text, setText] = useState('');
  const question = run.pending_question;
  const ended = run.state === 'terminal' || run.interrupted;
  const showQuestion = question && !ended && question.cancelled_at === null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!question || !available.answer || !/\S/.test(text)) return;
    await onAnswer(question.question_id, text);
  }

  if (ended && !message) return null;
  return (
    <section className="panel controls" aria-labelledby="controls-title">
      <h2 id="controls-title">{showQuestion ? 'The AI needs your input' : 'Run controls'}</h2>
      {showQuestion && (
        <div className="question">
          <p className="question-text">{question.question}</p>
          <p className="help">Asked <time dateTime={question.created_at}>{formatTime(question.created_at)}</time>. Your answer is clarification only; it does not change the original goal.</p>
          {question.answer
            ? <p className="answered"><strong>Your answer:</strong> {question.answer.text}</p>
            : (
              <form onSubmit={submit} className="answer-form">
                <label htmlFor="answer">Your answer</label>
                <textarea id="answer" rows={2} value={text} maxLength={8000} onChange={(e) => setText(e.target.value)} disabled={!available.answer} />
                <button type="submit" disabled={!available.answer || !/\S/.test(text)}>Send answer</button>
              </form>
            )}
        </div>
      )}
      {!ended && (
        <div className="actions">
          <button type="button" onClick={() => onControl('pause')} disabled={!available.pause}>Pause</button>
          <button type="button" onClick={() => onControl('resume')} disabled={!available.resume}>Resume</button>
          <button type="button" className="danger" onClick={() => onControl('cancel')} disabled={!available.cancel}>Cancel run</button>
          {busy && <span className="muted">Sending…</span>}
        </div>
      )}
      {!ended && <p className="help">Pause and cancel take effect after the current step settles. Resume takes a fresh screenshot before any new action.</p>}
      <div aria-live="polite" aria-atomic="true">
        {message && <p className={message.tone === 'error' ? 'error-text' : 'info-text'}>{message.text}</p>}
        {uncertain && <button type="button" className="secondary" onClick={onReconnect}>Reconnect</button>}
      </div>
    </section>
  );
}
