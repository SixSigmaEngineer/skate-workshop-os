const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const template = fs.readFileSync(path.join(__dirname, '../ui/templates/spotter-live.html'), 'utf8');
const renderSource = template.slice(template.indexOf('function recRender(status)'), template.indexOf('async function recPoll()'));

class Element {
  constructor(tag = 'span') { this.tag = tag; this.children = []; }
  set textContent(value) { this.children = [String(value)]; }
  get textContent() { return this.children.map(child => typeof child === 'string' ? child : child.textContent).join(''); }
  append(...children) { this.children.push(...children); }
  get links() { return this.children.filter(child => child.tag === 'a'); }
}

function renderer() {
  const scope = {
    document: {createElement: tag => new Element(tag)},
    recResult: new Element(), recStatusText: new Element(), recState: 'idle',
    recDot: {classList: {toggle: () => {}}}, recUpdateControls: () => {},
  };
  vm.createContext(scope);
  vm.runInContext(renderSource, scope);
  return scope;
}

test('completed recording offers one transcript link and one WAV link across repeated polls', () => {
  const ui = renderer();
  const status = {state: 'saved', url: '/entry/planning/note.md', audio_url: '/entry/planning/attachments/recording.wav'};
  for (let i = 0; i < 4; i++) ui.recRender(status);
  assert.equal(ui.recStatusText.textContent, 'Saved');
  assert.deepEqual(ui.recResult.links.map(link => [link.textContent, link.href]), [
    ['Open transcript note', status.url], ['Download audio (WAV)', status.audio_url],
  ]);
});

test('audio is available during transcription and remains downloadable after a failure', () => {
  const ui = renderer();
  const audio_url = '/entry/planning/attachments/recording.wav';
  ui.recRender({state: 'transcribing', progress: 42, audio_url});
  ui.recRender({state: 'transcribing', progress: 60, audio_url});
  assert.match(ui.recStatusText.textContent, /60%/);
  assert.equal(ui.recResult.links.length, 1);
  ui.recRender({state: 'error', error: 'Model unavailable. Audio saved.', audio_url});
  assert.match(ui.recResult.textContent, /Model unavailable/);
  assert.equal(ui.recResult.links[0].href, audio_url);
});

test('stopping and a failure without saved audio never show a stale download', () => {
  const ui = renderer();
  ui.recRender({state: 'saved', url: '/entry/old.md', audio_url: '/entry/old.wav'});
  ui.recRender({state: 'stopping'});
  assert.equal(ui.recResult.links.length, 0);
  ui.recRender({state: 'error', error: 'No audio captured.'});
  assert.equal(ui.recResult.links.length, 0);
  assert.equal(ui.recResult.textContent, 'No audio captured.');
});
