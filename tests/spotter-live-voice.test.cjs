const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const template = fs.readFileSync(path.join(__dirname, '../ui/templates/spotter-live.html'), 'utf8');
const source = template.slice(template.indexOf('// ---------- Speak replies'), template.indexOf('// ---------- Agent turns'));

function setup({saved = null, provider = 'openai', fetchImpl, playFailure = false} = {}) {
  const checkbox = {checked: false, addEventListener: (_, fn) => { checkbox.change = fn; }};
  const calls = [], audio = [], revoked = [], spoken = [];
  const storage = new Map(saved === null ? [] : [['skate.spotterLive.readRepliesAloud', saved]]);
  const scope = {
    SPEAK_ALOUD_FALLBACK: true, TTS_PROVIDER_FALLBACK: provider, roomActive: false,
    document: {getElementById: () => checkbox},
    localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value)},
    AbortController,
    window: {speechSynthesis: {cancel() {}, speak: u => spoken.push(u)}},
    SpeechSynthesisUtterance: class {constructor(text) {this.text = text;}},
    URL: {createObjectURL: () => 'blob:test', revokeObjectURL: url => revoked.push(url)},
    Audio: class {
      constructor(src) {this.src = src; audio.push(this);}
      play() {return playFailure ? Promise.reject(new Error('Playback blocked')) : Promise.resolve();}
      pause() {this.paused = true;}
    },
    fetch: async (...args) => {
      calls.push(args);
      if (fetchImpl) return fetchImpl(...args);
      if (args[0] === '/api/voice-config') return {ok: true, json: async () => ({tts_provider: provider, speak_aloud: true})};
      return {ok: true, headers: {get: () => 'audio/wav'}, blob: async () => ({})};
    },
  };
  vm.createContext(scope);
  vm.runInContext(source, scope);
  return {scope, checkbox, calls, audio, revoked, spoken, storage};
}

test('remembered text-only mode sends no speech requests and plays no audio', async () => {
  const ui = setup({saved: 'false'});
  await ui.scope.speak('Discuss independent review.');
  assert.equal(ui.checkbox.checked, false);
  assert.equal(ui.calls.length, 0);
  assert.equal(ui.spoken.length, 0);
});

test('turning voice off stops active audio and releases the waiting question', async () => {
  const ui = setup();
  const speaking = ui.scope.speak('Review the handoff.');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.audio.length, 1);
  ui.checkbox.checked = false;
  ui.checkbox.change();
  await speaking;
  assert.equal(ui.audio[0].paused, true);
  assert.deepEqual(ui.revoked, ['blob:test']);
  assert.equal(ui.storage.get('skate.spotterLive.readRepliesAloud'), 'false');
});

test('voice switched off during a pending request never plays its late response', async () => {
  let deliver;
  const ui = setup({fetchImpl: () => new Promise(resolve => {deliver = resolve;})});
  const speaking = ui.scope.speak('Review the handoff.');
  ui.checkbox.checked = false;
  ui.checkbox.change();
  deliver({ok: true, json: async () => ({tts_provider: 'openai'})});
  await speaking;
  assert.equal(ui.calls.length, 1);
  assert.equal(ui.calls[0][1].signal.aborted, true);
  assert.equal(ui.audio.length, 0);
  assert.equal(ui.spoken.length, 0);
});

test('audio errors and blocked playback release the question and audio URL', async () => {
  for (const playFailure of [false, true]) {
    const ui = setup({playFailure});
    const speaking = ui.scope.speak('Review the handoff.');
    await new Promise(resolve => setImmediate(resolve));
    if (!playFailure) ui.audio[0].onerror();
    await speaking;
    assert.deepEqual(ui.revoked, ['blob:test']);
  }
});

test('text-only questions still display answers and clear Thinking after recording stops', async () => {
  const ui = setup({saved: 'false'});
  const answers = [], statuses = [];
  Object.assign(ui.scope, {
    asking: false, askSendBtn: {disabled: false}, fileName: 'saved-meeting.md', AGENT_NAME: 'Spotter',
    setStatus: text => statuses.push(text), logQA: (q, a) => answers.push(a),
    appendToFile() {}, resumeRoom() {},
    fetch: async () => ({json: async () => ({ok: true, answer: 'Review the handoff.'})}),
  });
  vm.runInContext(template.slice(template.indexOf('async function askAgent('), template.indexOf('// Run a coaching stance')), ui.scope);
  await ui.scope.askAgent('What next?');
  assert.deepEqual(answers, ['Review the handoff.']);
  assert.equal(statuses.at(-1), 'Idle');
  assert.equal(ui.scope.askSendBtn.disabled, false);
  assert.equal(ui.audio.length, 0);
});
