/* Keep complete evidence searchable while bounding the graph's working set. */
(function (root) {
  class GraphDetail {
    constructor(nodes, edges, pageSize = 40, notePageSize = 80) {
      this.allNodes = nodes;
      this.allEdges = edges;
      this.byId = new Map(nodes.map(node => [node.id, node]));
      this.notes = nodes.filter(node => !node.is_signal);
      this.byParent = new Map();
      for (const node of nodes) {
        if (!node.is_signal || !this.byId.has(node.parent)) continue;
        if (!this.byParent.has(node.parent)) this.byParent.set(node.parent, []);
        this.byParent.get(node.parent).push(node);
      }
      this.total = [...this.byParent.values()].reduce((sum, signals) => sum + signals.length, 0);
      this.pageSize = pageSize;
      this.notePageSize = notePageSize;
      this.notePage = 0;
      this.parent = '';
      this.type = '';
      this.page = 0;
      this.expanded = false;
    }

    select(id, activeTypes = new Set()) {
      const node = this.byId.get(id);
      if (!node) return false;
      this.locateParent = true;
      const parent = node.is_signal ? node.parent : node.id;
      if (parent !== this.parent) {
        this.parent = parent;
        this.page = 0;
        this.type = '';
      }
      if (node.is_signal) {
        this.expanded = true;
        if (this.type !== node.entry_type) this.type = '';
        const matching = (this.byParent.get(parent) || []).filter(item => (!this.type || item.entry_type === this.type)
          && (!activeTypes.size || activeTypes.has(item.entry_type)));
        this.page = Math.floor(matching.findIndex(item => item.id === id) / this.pageSize);
      }
      return true;
    }

    snapshot(activeTypes = new Set()) {
      const signals = this.byParent.get(this.parent) || [];
      const matchesType = node => !activeTypes.size || activeTypes.has(node.entry_type);
      const filtered = signals.filter(node => (!this.type || node.entry_type === this.type) && matchesType(node));
      const pages = Math.max(1, Math.ceil(filtered.length / this.pageSize));
      this.page = Math.max(0, Math.min(this.page, pages - 1));
      let pageSignals = this.expanded ? filtered.slice(this.page * this.pageSize, (this.page + 1) * this.pageSize) : [];
      // Keep a parent visible when its children match a legend filter.
      const matchingNotes = this.notes.filter(node => matchesType(node)
        || node.id === this.parent
        || (this.byParent.get(node.id) || []).some(matchesType));
      const notePages = Math.max(1, Math.ceil(matchingNotes.length / this.notePageSize));
      if (this.locateParent) {
        const index = matchingNotes.findIndex(node => node.id === this.parent);
        if (index >= 0) this.notePage = Math.floor(index / this.notePageSize);
        this.locateParent = false;
      }
      this.notePage = Math.max(0, Math.min(this.notePage, notePages - 1));
      const notes = matchingNotes.slice(this.notePage * this.notePageSize, (this.notePage + 1) * this.notePageSize);
      if (!notes.some(node => node.id === this.parent)) pageSignals = [];
      const nodes = [...notes, ...pageSignals];
      const ids = new Set(nodes.map(node => node.id));
      const edges = this.allEdges.filter(edge => ids.has(edge.from) && ids.has(edge.to));
      return {nodes, edges, signals, filtered, pageSignals, pages, page: this.page,
        start: filtered.length ? this.page * this.pageSize + 1 : 0,
        end: Math.min((this.page + 1) * this.pageSize, filtered.length), notes: notes.length,
        noteTotal: matchingNotes.length, notePages, notePage: this.notePage,
        noteStart: matchingNotes.length ? this.notePage * this.notePageSize + 1 : 0,
        noteEnd: Math.min((this.notePage + 1) * this.notePageSize, matchingNotes.length)};
    }
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = GraphDetail;
  else root.SkateGraphDetail = GraphDetail;
})(typeof window !== 'undefined' ? window : globalThis);
