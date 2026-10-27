import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { PendingQuestion } from '../console.ts';
import { formatTime } from '../history.ts';
import type { Message } from './RunHeader.tsx';

interface Props {
  question: PendingQuestion;
  canAnswer: boolean;
  canResume: boolean;
  busy: boolean;
  uncertain: boolean;
  message: Message | null;
  onAnswer: (questionId: string, text: string) => void;
  onResume: () => void;
  onReconnect: () => void;
}

/** The AI is waiting on the user: question, answer field and, once answered, the way to let the run continue. */
export function QuestionBlock({ question, canAnswer, canResume, busy, uncertain, message, onAnswer, onResume, onReconnect }: Props) {
  const [text, setText] = useState('');
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  const answered = question.answer !== null;

  const focusedFor = useRef<string | null>(null);

  // Focus the answer field once per question, when it first becomes answerable; later busy or
  // connection changes never steal focus again.
  useEffect(() => {
    if (answered || !canAnswer || focusedFor.current === question.question_id) return;
    focusedFor.current = question.question_id;
    fieldRef.current?.focus();
  }, [question.question_id, answered, canAnswer]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!canAnswer || !/\S/.test(text)) return;
    onAnswer(question.question_id, text);
  }

  return (
    <section className="question-block" aria-labelledby="question-title">
      <h2 id="question-title" className="question-flag">{answered ? 'Your answer is recorded' : 'The AI needs your input'}</h2>
      <p id="question-text" className="question-text">{question.question}</p>
      <p className="help">Asked <time dateTime={question.created_at}>{formatTime(question.created_at)}</time>. Your answer is clarification only; it does not change the original goal.</p>
      {question.answer
        ? (
          <>
            <p className="answered"><strong>Your answer:</strong> {question.answer.text}</p>
            <div className="actions">
              <button type="button" onClick={onResume} disabled={!canResume}>Resume</button>
              {busy && <span className="muted">Sending…</span>}
            </div>
          </>
        )
        : (
          <form onSubmit={submit} className="answer-form">
            <label htmlFor="answer">Your answer</label>
            <textarea id="answer" ref={fieldRef} aria-describedby="question-text" rows={3} value={text} maxLength={8000} onChange={(e) => setText(e.target.value)} disabled={!canAnswer} />
            <div className="actions">
              <button type="submit" disabled={!canAnswer || !/\S/.test(text)}>Send answer</button>
              <span className="help">{busy ? 'Sending…' : 'Once your answer is recorded, the run resumes if it can; otherwise a message says why.'}</span>
            </div>
          </form>
        )}
      <div aria-live="polite" aria-atomic="true" className="question-feedback">
        {message && <p className={message.tone === 'error' ? 'error-text' : 'info-text'}>{message.text}</p>}
        {uncertain && message && <button type="button" className="secondary" onClick={onReconnect}>Reconnect</button>}
      </div>
    </section>
  );
}
