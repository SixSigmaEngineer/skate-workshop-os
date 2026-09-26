const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

function setup(source, {failure = false} = {}) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      value: '', children: [], hidden: false, addEventListener(type, fn) {this[type] = fn;},
      replaceChildren() {this.children = [];}, append(child) {this.children.push(child);},
      get childElementCount() {return this.children.length;}, scrollIntoView() {},
    });
    return elements.get(id);
  }
  element('body').value = source;
  const archives = [];
  let refreshed = false;
  const scope = {
    URLSearchParams, Blob, document: {getElementById: element, createElement: () => ({})},
    saveDraft() {}, refreshSummarizeAvailability() {}, refreshAttachGallery() {},
    fetch: async (url, options) => {
      archives.push({url, text: await options.body.text()});
      return {ok: !failure, json: async () => failure ? {ok:false, error:'Disk full'} : {ok:true, path:`attachments/original-note-${archives.length}.txt`}};
    },
    window: {refreshNoteOriginals: () => {refreshed = true;}},
  };
  vm.createContext(scope);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../ui/static/note-cleanup.js'), 'utf8'), scope);
  return {scope, element, archives, refreshed: () => refreshed};
}

test('cleanup archives the entire dirty note before applying reviewed notes', async () => {
  const raw = 'um, staff review forms\r\n#A: Maria will check the intake form.\r\n';
  const ui = setup(raw);
  ui.scope.showCleanupPreview({markdown:'## Cleaned Notes\n\nStaff review intake.\n\n#A: Maria will check the intake form.'});
  await ui.element('applyCleanup').click();
  assert.equal(ui.archives[0].text, raw);
  assert.match(ui.archives[0].url, /session=note-originals/);
  assert.match(ui.element('body').value, /#A: Maria will check/);
  assert.match(ui.element('body').value, /\/entry\/note-originals\/attachments\/original-note-1.txt/);
  assert.equal(ui.refreshed(), true);
});

test('repeated cleanup retains every prior original link', async () => {
  const ui = setup('Original dirty draft');
  ui.scope.showCleanupPreview({markdown:'First clean version'});
  await ui.element('applyCleanup').click();
  const firstClean = ui.element('body').value;
  ui.scope.showCleanupPreview({markdown:'Second clean version'});
  await ui.element('applyCleanup').click();
  assert.equal(ui.archives[1].text, firstClean);
  assert.match(ui.element('body').value, /original-note-1.txt/);
  assert.match(ui.element('body').value, /original-note-2.txt/);
});

test('transcript summary retains the complete raw transcript as its original', async () => {
  const raw = 'Meeting intro\n\n## Raw Transcript\n' + 'Staff review the intake form.\n'.repeat(1000) + 'Last sentence.';
  const ui = setup(raw);
  ui.scope.showCleanupPreview({markdown:'## Meeting Notes\nStaff review intake.', summary:{tags:[]}});
  await ui.element('applyCleanup').click();
  assert.equal(ui.archives[0].text, raw);
  assert.match(ui.element('body').value, /Meeting intro/);
  assert.match(ui.element('body').value, /Original notes \/ transcript/);
});

test('failed archival never replaces the dirty notes', async () => {
  const ui = setup('Keep these dirty notes', {failure:true});
  ui.scope.showCleanupPreview({markdown:'Replacement'});
  await ui.element('applyCleanup').click();
  assert.equal(ui.element('body').value, 'Keep these dirty notes');
  assert.equal(ui.element('cleanupReviewStatus').textContent, 'Disk full');
});
