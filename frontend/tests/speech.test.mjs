import assert from 'node:assert/strict';
import { test } from 'node:test';
import { apiRequest } from '../src/console.ts';
import { appendTranscript, canDictate, pickRecordingType, transcribe } from '../src/speech.ts';

test('recording type prefers webm/opus and refuses formats the server rejects', () => {
  assert.equal(pickRecordingType(() => true), 'audio/webm;codecs=opus');
  assert.equal(pickRecordingType((t) => t === 'audio/mp4'), 'audio/mp4');
  assert.equal(pickRecordingType((t) => t === 'audio/ogg'), null);
});

test('dictation needs a secure context, media devices and MediaRecorder', () => {
  const ok = { isSecureContext: true, mediaDevices: {}, MediaRecorder: function MediaRecorder() {} };
  assert.equal(canDictate(ok), true);
  assert.equal(canDictate({ ...ok, isSecureContext: false }), false);
  assert.equal(canDictate({ ...ok, mediaDevices: undefined }), false);
  assert.equal(canDictate({ ...ok, MediaRecorder: undefined }), false);
});

test('dictated text is appended with one space, ignored when blank, and bounded', () => {
  assert.equal(appendTranscript('', '  Open the fictional app ', 100), 'Open the fictional app');
  assert.equal(appendTranscript('Open the app', 'then tap Save', 100), 'Open the app then tap Save');
  assert.equal(appendTranscript('Open the app\n', 'then tap Save', 100), 'Open the app\nthen tap Save');
  assert.equal(appendTranscript('Keep me', '   ', 100), 'Keep me');
  assert.equal(appendTranscript('abc', 'defgh', 6), 'abc de');
});

test('transcription posts raw audio with its type and the console guard header', async () => {
  const requests = [];
  const fetcher = async (url, options) => {
    requests.push([url, options]);
    return new Response(JSON.stringify({ text: 'Fictional goal', model: 'gpt-transcribe' }), { status: 200 });
  };
  const recording = new Blob(['fake-audio'], { type: 'audio/webm' });
  const result = await transcribe(recording, (path, options) => apiRequest(path, options, fetcher));
  assert.deepEqual(result, { text: 'Fictional goal', model: 'gpt-transcribe' });
  const [url, options] = requests[0];
  assert.equal(url, '/api/transcriptions');
  assert.equal(options.method, 'POST');
  assert.equal(options.body, recording);
  assert.equal(options.headers['Content-Type'], 'audio/webm');
  assert.equal(options.headers['X-Visto'], 'local-console');
});

test('transcription rejects malformed replies and surfaces server detail', async () => {
  await assert.rejects(transcribe(new Blob(['x']), async () => ({ text: 3 })), /Invalid transcription response/);
  const fetcher = async () => new Response(JSON.stringify({ detail: 'Transcription failed (provider: http_401)' }), { status: 502 });
  await assert.rejects(
    transcribe(new Blob(['x'], { type: 'audio/webm' }), (path, options) => apiRequest(path, options, fetcher)),
    /provider: http_401/,
  );
});
