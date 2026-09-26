const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../ui/static/live-workspace.js'), 'utf8');
const template = fs.readFileSync(path.join(__dirname, '../ui/templates/spotter-live.html'), 'utf8');

function workspace(parent) {
  const elements = [];
  const scope = {
    URL, Event, location: {href: 'http://localhost/spotter-live', origin: 'http://localhost', pathname: '/spotter-live', search: ''},
    dispatchEvent() {},
    document: {
      body: {style: {}, append() {}}, addEventListener() {}, querySelectorAll: () => [],
      createElement(tag) {
        const element = {tag, children: [], hidden: false, append(...children) {this.children.push(...children);}, addEventListener(type, fn) {this[type] = fn;}};
        elements.push(element);
        return element;
      },
    },
  };
  scope.window = scope;
  scope.parent = parent || scope;
  vm.runInNewContext(source, scope);
  return {scope, elements};
}

test('switching notes and live repeatedly keeps both documents instead of navigating away', () => {
  const {scope, elements} = workspace();
  scope.SKATENavigate('/new?tab=draft-1');
  const frame = elements.find(el => el.tag === 'iframe');
  const panel = elements.find(el => el.tag === 'section');
  frame.unsavedDraft = 'Keep this note';
  scope.SKATELiveWorkspace.showLive();
  assert.equal(panel.hidden, true);
  scope.SKATELiveWorkspace.showPage();
  assert.equal(panel.hidden, false);
  assert.equal(frame.unsavedDraft, 'Keep this note');
  assert.equal(frame.src, 'http://localhost/new?tab=draft-1');
  assert.equal(elements.filter(el => el.tag === 'iframe').length, 1);
  assert.equal(scope.location.href, 'http://localhost/spotter-live');
});

test('Spotter Live navigation from the note returns to the existing live host', () => {
  let returns = 0;
  const {scope, elements} = workspace({SKATELiveWorkspace: {showLive() {returns++;}}});
  scope.SKATENavigate('/spotter-live#meeting-recorder');
  assert.equal(returns, 1);
  assert.equal(elements.length, 0);
});

function recorder(status, overrides = {}) {
  const loads = [], starts = [];
  const scope = {
    recState: 'idle', fileName: '', roomActive: false, recCommandPending: false, recTimer: null,
    recSession: {}, recSource: {}, recMic: {}, toggleBtn: {},
    document: {getElementById: () => ({style: {}})},
    fetch: async () => ({json: async () => status}),
    recRender(s) {scope.recState = s.state;}, updateToggleUI() {}, refreshTranscriptHistory() {},
    async loadTranscript(file) {loads.push(file); scope.fileName = file;},
    async startRoom() {starts.push(scope.fileName); scope.roomActive = true;},
    setInterval() {return 1;}, clearInterval() {}, ...overrides,
  };
  vm.runInNewContext(template.slice(template.indexOf('async function recPoll()'), template.indexOf('async function recorderCommand(')), scope);
  return {scope, loads, starts};
}

test('returning to a running recorder loads saved captions before reconnecting once', async () => {
  const ui = recorder({state: 'recording', live_file: 'current.md', session: 'alpha', source: 'system', include_mic: true});
  await ui.scope.recPoll();
  await ui.scope.recPoll();
  assert.deepEqual(ui.loads, ['current.md']);
  assert.deepEqual(ui.starts, ['current.md']);
  assert.equal(ui.scope.recSession.value, 'alpha');
});

test('a newly started recording overrides an older selected transcript', async () => {
  const ui = recorder({state: 'recording', live_file: 'new.md'}, {fileName: 'old.md'});
  await ui.scope.recPoll();
  assert.deepEqual(ui.loads, ['new.md']);
  assert.deepEqual(ui.starts, ['new.md']);
});

test('an idle saved recorder does not replace the selected historical transcript', async () => {
  const ui = recorder({state: 'saved', live_file: 'latest.md'}, {fileName: 'historical.md'});
  await ui.scope.recPoll();
  assert.deepEqual(ui.loads, []);
  assert.deepEqual(ui.starts, []);
});

test('finishing transcription refreshes the final transcript without restarting capture', async () => {
  const ui = recorder({state: 'saved', live_file: 'current.md'}, {recState: 'transcribing', fileName: 'current.md'});
  await ui.scope.recPoll();
  assert.deepEqual(ui.loads, ['current.md']);
  assert.deepEqual(ui.starts, []);
});
