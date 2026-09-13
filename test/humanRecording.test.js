import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../integrations/voice/human.html', import.meta.url), 'utf8')
  .match(/<script type="module">([\s\S]*?)<\/script>/)[1];

class Events {
  constructor() { this.listeners = new Map(); }
  addEventListener(name, listener, options = {}) {
    this.listeners.set(name, [...(this.listeners.get(name) || []), { listener, once: options.once }]);
  }
  removeEventListener(name, listener) {
    this.listeners.set(name, (this.listeners.get(name) || []).filter(item => item.listener !== listener));
  }
  emit(name, event = {}) {
    for (const item of [...(this.listeners.get(name) || [])]) {
      if (item.once) this.removeEventListener(name, item.listener);
      item.listener(event);
    }
  }
  close() { this.emit('close'); }
  send() {}
}

function browser({ stalledUpload = false, stalledRecorder = false } = {}) {
  const elements = Object.fromEntries(['start', 'stop', 'status', 'audio', 'captions'].map(name => {
    const element = new Events();
    Object.assign(element, { disabled: false, textContent: '', srcObject: null,
      play: async () => {}, replaceChildren() {}, append() {} });
    return [name, element];
  }));
  const requests = [], recorders = [], microphones = [], timers = new Map();
  let counter = 0, timerId = 0, resolveUpload;
  class Stream {
    constructor(tracks) { this.tracks = tracks; }
    getTracks() { return this.tracks; }
    getAudioTracks() { return this.tracks; }
  }
  class Peer extends Events {
    constructor() { super(); this.iceGatheringState = 'complete'; }
    addTrack() {}
    createDataChannel() { return new Events(); }
    async createOffer() { return { sdp: 'offer' }; }
    async setLocalDescription(offer) { this.localDescription = offer; }
    async setRemoteDescription() { this.emit('track', { track: {} }); }
  }
  class Recorder extends Events {
    constructor() { super(); this.state = 'inactive'; this.tail = `call-${recorders.length + 1}`; recorders.push(this); }
    start() { this.state = 'recording'; }
    stop() {
      this.state = 'inactive';
      if (!stalledRecorder) queueMicrotask(() => {
        this.emit('dataavailable', { data: new Blob([this.tail]) });
        this.emit('stop');
      });
    }
  }
  class Mixer {
    createMediaStreamDestination() { return { stream: new Stream([]) }; }
    createMediaStreamSource() { return { connect() {} }; }
    async close() { this.closed = true; }
  }
  const context = vm.createContext({ Blob, AbortController, RTCPeerConnection: Peer, AudioContext: Mixer,
    MediaStream: Stream, MediaRecorder: Recorder, queueMicrotask,
    setTimeout(fn, delay) { const id = ++timerId; timers.set(id, { fn, delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
    document: { getElementById: name => elements[name] },
    window: new Events(), location: { pathname: '/s/token/' },
    navigator: { mediaDevices: { async getUserMedia() {
      const track = { stopped: false, stop() { this.stopped = true; } };
      microphones.push(track); return new Stream([track]);
    } } },
    async fetch(url, options) {
      if (url.endsWith('/api/session')) return { ok: true, json: async () => ({ sdp: 'answer', attempt_id: `attempt-${++counter}` }) };
      requests.push({ url, body: options.body });
      if (stalledUpload && requests.length === 1) return new Promise(resolve => { resolveUpload = resolve; });
      return { ok: true };
    },
  });
  vm.runInContext(source, context);
  return { elements, requests, recorders, microphones,
    start: () => elements.start.listeners.get('click')[0].listener(),
    stop: () => elements.stop.emit('click'),
    cleanup: () => vm.runInContext('cleanup(activeCall)', context),
    finishFirstUpload: () => resolveUpload({ ok: true }),
    fireTimers(delay) { for (const [id, timer] of [...timers]) if (timer.delay === delay) { timers.delete(id); timer.fn(); } },
  };
}

async function settle() { for (let n = 0; n < 10; n++) await Promise.resolve(); }

test('short calls flush the final recording chunk and cleanup is idempotent', async () => {
  const b = browser();
  await b.start();
  b.cleanup(); b.cleanup();
  assert.equal(b.microphones[0].stopped, true);
  assert.equal(b.elements.start.disabled, false);
  await settle();
  assert.equal(b.requests.length, 1);
  assert.equal(b.requests[0].url, '/s/token/api/recording?attempt=attempt-1');
  assert.equal(await b.requests[0].body.text(), 'call-1');
  assert.match(b.elements.status.textContent, /Recording saved/);
});

test('consecutive calls do not share audio or attempt IDs while an earlier upload is pending', async () => {
  const b = browser({ stalledUpload: true });
  await b.start(); b.cleanup(); await settle();
  assert.equal(b.microphones[0].stopped, true);
  await b.start(); b.cleanup(); await settle();
  assert.equal(b.requests.length, 2);
  assert.equal(await b.requests[0].body.text(), 'call-1');
  assert.equal(await b.requests[1].body.text(), 'call-2');
  assert.match(b.requests[1].url, /attempt=attempt-2$/);
  const newerStatus = b.elements.status.textContent;
  b.finishFirstUpload(); await settle();
  assert.equal(b.elements.status.textContent, newerStatus);
});

test('a missing recorder stop event never keeps the microphone on or uploads partial audio', async () => {
  const b = browser({ stalledRecorder: true });
  await b.start(); b.cleanup();
  assert.equal(b.microphones[0].stopped, true);
  assert.equal(b.elements.start.disabled, false);
  b.fireTimers(2000); await settle();
  assert.equal(b.requests.length, 0);
  assert.match(b.elements.status.textContent, /No complete audio recording/);
});

test('hangup stops capture immediately even when the peer never acknowledges closure', async () => {
  const b = browser();
  await b.start(); b.stop();
  assert.equal(b.microphones[0].stopped, true);
  b.fireTimers(1500); await settle();
  assert.equal(b.elements.start.disabled, false);
  assert.equal(b.requests.length, 1);
});
