(() => {
  const host = document.getElementById('noteOriginals');
  const list = document.getElementById('noteOriginalsList');
  const editor = document.getElementById('body');
  let currentIds = '';
  function sources() {
    if (!editor) return JSON.parse(document.getElementById('noteOriginalsData').textContent || '[]');
    const session = (typeof attachSessionValue === 'function' ? attachSessionValue() : 'unassigned').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'unassigned';
    const matches = [...editor.value.matchAll(/\]\(((?:attachments\/|\/entry\/[a-z0-9][a-z0-9_-]*\/attachments\/)original-note-[A-Za-z0-9._-]+\.txt)\)/g)];
    return [...new Set(matches.map(match => match[1].startsWith('/entry/') ? match[1].slice(7) : session + '/' + match[1]))].map(source_id => ({source_id, url: '/entry/' + source_id}));
  }
  window.refreshNoteOriginals = (openLatest = false) => {
    const rows = sources();
    const ids = JSON.stringify(rows.map(row => row.source_id));
    host.hidden = rows.length === 0;
    if (ids === currentIds) return;
    currentIds = ids;
    list.replaceChildren();
    rows.forEach((row, index) => {
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = index === 0 ? 'Original text — before first cleanup' : `Text before cleanup ${index + 1}`;
      const text = document.createElement('textarea');
      text.readOnly = true; text.rows = 12;
      text.setAttribute('aria-label', summary.textContent);
      const status = document.createElement('p');
      status.className = 'field-help'; status.setAttribute('role', 'status');
      const more = document.createElement('button');
      more.type = 'button'; more.className = 'button'; more.textContent = 'Load more original text'; more.hidden = true;
      const download = document.createElement('a');
      download.href = row.url; download.download = ''; download.textContent = 'Download complete original';
      let next = 0, loaded = false, loading = false;
      async function load() {
        if (loading || next === null) return;
        loading = true; more.disabled = true;
        status.textContent = 'Opening preserved original…';
        try {
          const response = await fetch('/api/note-originals?' + new URLSearchParams({source_id: row.source_id, offset: next}));
          const data = await response.json();
          if (!response.ok || !data.ok) throw new Error(data.error || 'Could not open the original.');
          text.value += data.text;
          next = data.next_offset; loaded = true;
          status.textContent = next === null ? 'Complete original text. Read-only.' : `${text.value.length} of ${data.total_chars} characters shown. The complete original is preserved.`;
          more.hidden = next === null;
        } catch (error) { status.textContent = error.message; }
        finally { loading = false; more.disabled = false; }
      }
      details.addEventListener('toggle', () => { if (details.open && !loaded) load(); });
      more.addEventListener('click', load);
      details.append(summary, text, status, more, download);
      list.append(details);
      if (openLatest && index === rows.length - 1) details.open = true;
    });
  };
  if (editor) editor.addEventListener('change', () => window.refreshNoteOriginals());
  document.addEventListener('DOMContentLoaded', () => window.refreshNoteOriginals(), {once:true});
  window.refreshNoteOriginals();
})();
