const test = require('node:test');
const assert = require('node:assert/strict');
const GraphDetail = require('../ui/static/graph-detail.js');

function fixture(noteCount = 35, signalCount = 910) {
  const notes = Array.from({length: noteCount}, (_, i) => ({id:`note-${i}`, entry_type:'note'}));
  const signals = Array.from({length: signalCount}, (_, i) => ({id:`signal-${i}`, parent:'note-0',
    is_signal:true, entry_type: i % 2 ? 'action' : 'pain', title_full:`Distinct evidence ${i}`}));
  const edges = signals.map(node => ({from:node.parent, to:node.id, type:'contains'}));
  edges.push({from:'note-0', to:`note-${noteCount-1}`, type:'supports'});
  return {nodes:[...notes, ...signals], edges};
}

test('910 signals stay available without entering the initial layout', () => {
  const data = fixture();
  const before = JSON.stringify(data);
  const model = new GraphDetail(data.nodes, data.edges);
  const overview = model.snapshot();
  assert.equal(overview.nodes.length, 35);
  assert.equal(overview.pageSignals.length, 0);
  assert.equal(overview.edges.length, 1);
  assert.equal(model.total, 910);
  assert.equal(model.allNodes.length, 945);
  assert.equal(JSON.stringify(data), before);
});

test('every signal is reachable in bounded pages, including the last partial page', () => {
  const data = fixture();
  const model = new GraphDetail(data.nodes, data.edges);
  model.select('note-0');
  model.expanded = true;
  const seen = [];
  for (let page = 0; page < 23; page++) {
    model.page = page;
    const view = model.snapshot();
    assert.ok(view.nodes.length <= 75);
    assert.ok(view.pageSignals.length <= 40);
    const ids = new Set(view.nodes.map(node => node.id));
    assert.ok(view.edges.every(edge => ids.has(edge.from) && ids.has(edge.to)));
    seen.push(...view.pageSignals.map(node => node.id));
  }
  assert.equal(seen.length, 910);
  assert.equal(new Set(seen).size, 910);
  assert.equal(seen.at(-1), 'signal-909');
});

test('search selection reveals a signal outside the current page', () => {
  const data = fixture();
  const model = new GraphDetail(data.nodes, data.edges);
  model.select('signal-909');
  const view = model.snapshot();
  assert.equal(view.page, 22);
  assert.ok(view.nodes.some(node => node.id === 'signal-909'));
  assert.ok(view.nodes.some(node => node.id === 'note-0'));
});

test('type filters page the full set and preserve context when selecting a signal', () => {
  const data = fixture();
  const model = new GraphDetail(data.nodes, data.edges);
  model.select('note-0');
  model.expanded = true;
  model.type = 'action';
  model.page = 7;
  let view = model.snapshot(new Set(['action']));
  assert.equal(view.filtered.length, 455);
  assert.equal(view.notes, 1);
  assert.ok(view.pageSignals.every(node => node.entry_type === 'action'));
  model.select(view.pageSignals[10].id, new Set(['action']));
  view = model.snapshot(new Set(['action']));
  assert.equal(model.type, 'action');
  assert.equal(view.page, 7);
});

test('large workshop collections also have a bounded note overview', () => {
  const data = fixture(2000, 10000);
  const model = new GraphDetail(data.nodes, data.edges);
  assert.equal(model.snapshot().nodes.length, 80);
  model.select('note-1999');
  let view = model.snapshot();
  assert.equal(view.notePage, 24);
  assert.ok(view.nodes.some(node => node.id === 'note-1999'));
  model.select('signal-9999');
  view = model.snapshot();
  assert.equal(view.notePage, 0);
  assert.ok(view.nodes.length <= 120);
  assert.ok(view.nodes.some(node => node.id === 'signal-9999'));
});

test('legend filtering keeps parents of matching signals and removes unrelated notes', () => {
  const data = fixture();
  const model = new GraphDetail(data.nodes, data.edges);
  const view = model.snapshot(new Set(['pain']));
  assert.deepEqual(view.nodes.map(node => node.id), ['note-0']);
  assert.equal(view.pageSignals.length, 0);
});

test('collapse and switching to a note without signals remove all satellites', () => {
  const data = fixture();
  const model = new GraphDetail(data.nodes, data.edges);
  model.select('signal-909');
  model.expanded = false;
  assert.equal(model.snapshot().pageSignals.length, 0);
  model.select('note-1');
  model.expanded = true;
  const view = model.snapshot();
  assert.equal(view.signals.length, 0);
  assert.equal(view.pageSignals.length, 0);
});

test('empty and unmatched views have valid pages and no orphaned edges', () => {
  const model = new GraphDetail([], []);
  assert.equal(model.select('missing'), false);
  model.page = model.notePage = 99;
  const view = model.snapshot(new Set(['action']));
  assert.equal(view.nodes.length, 0);
  assert.equal(view.page, 0);
  assert.equal(view.notePage, 0);
  assert.equal(view.start, 0);
  assert.equal(view.noteStart, 0);
});
