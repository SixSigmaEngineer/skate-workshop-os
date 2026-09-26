const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {visit, recordingMessage} = require('../ui/static/app-navigation.js');

test('page history ignores reloads and unsafe destinations', () => {
  let pages = visit([], '/sessions');
  pages = visit(pages, '/sessions');
  pages = visit(pages, '/lineup?session=alpha');
  assert.deepEqual(pages, ['/sessions', '/lineup?session=alpha']);
  assert.deepEqual(visit(['//outside.example', '/api/speak'], '/new?tab=one'), ['/new?tab=one']);
  assert.deepEqual(visit({}, '/'), ['/']);
});

test('recorder status distinguishes capturing, processing, success, and recoverable failures', () => {
  assert.match(recordingMessage({state:'recording', elapsed:125}), /2:05.*continues/);
  assert.match(recordingMessage({state:'stopping'}), /Saving your audio/);
  assert.match(recordingMessage({state:'transcribing', progress:42}), /Audio saved.*42%/);
  assert.match(recordingMessage({state:'saved'}), /Audio and transcript saved/);
  assert.match(recordingMessage({state:'error', audio_url:'/saved.wav'}), /saved audio is available/);
  assert.doesNotMatch(recordingMessage({state:'error'}), /saved audio/);
  assert.equal(recordingMessage({state:'idle'}), '');
});

test('Back returns to the preceding screen without a browser POST resubmission', () => {
  let click, destination;
  const storage = new Map([['skate-page-history:main', JSON.stringify(['/sessions', '/lineup'])]]);
  const scope = {
    location: {pathname:'/lineup/new', search:''},
    sessionStorage: {getItem:key => storage.get(key), setItem:(key,value) => storage.set(key,value)},
    document: {querySelector: selector => selector === '[data-app-back]' ? {addEventListener: (_,fn) => {click = fn;}} : null},
    SKATENavigate: url => {destination = url;},
  };
  scope.window = scope; scope.parent = scope;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../ui/static/app-navigation.js'), 'utf8'), scope);
  click();
  assert.equal(destination, '/sessions');
  assert.deepEqual(JSON.parse(storage.get('skate-page-history:main')), ['/sessions']);
});
