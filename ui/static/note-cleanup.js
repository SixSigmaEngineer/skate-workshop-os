let pendingCleanup = null;
let cleanupController = null;

async function requestReviewedCleanup(kind, payload) {
  if (cleanupController) throw new Error('A cleanup is already running. Wait or choose Stop cleanup.');
  const controller = new AbortController();
  cleanupController = controller;
  const button = document.getElementById('compressBtn');
  const originalLabel = button.innerHTML;
  const stop = document.getElementById('stopCleanupBtn');
  const progress = document.getElementById('compressProgress');
  const progressText = document.getElementById('compressProgressText');
  const elapsed = document.getElementById('compressElapsed');
  const startedAt = Date.now();
  const updateElapsed = () => {
    const seconds = Math.floor((Date.now() - startedAt) / 1000);
    elapsed.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  };
  button.disabled = true;
  button.setAttribute('aria-busy', 'true');
  button.innerHTML = '<img class="button-icon" src="/static/icons/wand.svg" alt="">Working…';
  document.getElementById('summarizeTranscriptBtn').disabled = true;
  pendingCleanup = null;
  document.getElementById('cleanupPreview').hidden = true;
  stop.hidden = false;
  stop.disabled = false;
  progress.hidden = false;
  progressText.textContent = 'Preparing the complete note…';
  updateElapsed();
  const timer = setInterval(updateElapsed, 1000);
  try {
    const response = await fetch('/api/cleanup/stream', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({...payload, kind}), signal: controller.signal
    });
    if (!response.ok) {
      const failure = await response.json();
      throw new Error(failure.error || 'Could not start cleanup.');
    }
    if (!response.body) throw new Error('This window could not read cleanup progress. Reopen SKATE and try again.');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let result = null;
    function receive(line) {
      if (!line.trim()) return;
      const event = JSON.parse(line);
      if (event.type === 'progress') {
        const label = `${event.provider}: ${event.completed} of ${event.total} sections complete`;
        progressText.textContent = label;
        document.getElementById('statusLine').textContent = label + (event.provider_issue ? '. ' + event.provider_issue : '.');
      } else if (event.type === 'result') {
        result = event.data;
      } else if (event.type === 'error') {
        throw new Error(event.error);
      }
    }
    while (true) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value, {stream: !done});
      const lines = buffer.split('\n');
      buffer = lines.pop();
      lines.forEach(receive);
      if (done) { receive(buffer); break; }
    }
    if (!result) throw new Error('Cleanup was interrupted. Your original note is still in the editor.');
    if (!result.ok) throw new Error(result.error || 'Cleanup could not finish.');
    return result;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Cleanup stopped. Your original note is still in the editor.');
    throw error;
  } finally {
    // Also close the stream after parsing/network errors, stopping queued work.
    controller.abort();
    clearInterval(timer);
    cleanupController = null;
    stop.hidden = true;
    progress.hidden = true;
    button.disabled = false;
    button.removeAttribute('aria-busy');
    button.innerHTML = originalLabel;
    refreshSummarizeAvailability();
  }
}

document.getElementById('stopCleanupBtn').addEventListener('click', () => {
  document.getElementById('stopCleanupBtn').disabled = true;
  cleanupController?.abort();
});

function showCleanupPreview(data, selection = null) {
  const source = document.getElementById('body').value;
  pendingCleanup = {source, data, selection};
  document.getElementById('cleanupText').value = data.markdown || '';
  document.getElementById('cleanupReviewStatus').textContent = data.message || 'Review the proposed notes.';
  const host = document.getElementById('cleanupExclusions');
  host.replaceChildren();
  const review = data.review || {};
  const append = text => { const p = document.createElement('p'); p.textContent = text; host.append(p); };
  (review.excluded || []).forEach(item => append(item.reason + ': ' + item.text));
  (review.excluded_topics || []).forEach(topic => append('Model excluded topic: ' + topic));
  if (review.exclusions_truncated) append('Showing the first 100 exclusions. The full original will be kept in a text attachment.');
  if (!host.childElementCount) append('No clear off-topic segments were identified.');
  const preview = document.getElementById('cleanupPreview');
  preview.hidden = false;
  preview.scrollIntoView({behavior: 'smooth', block: 'start'});
}
document.getElementById('cancelCleanup').addEventListener('click', () => {
  document.getElementById('cleanupPreview').hidden = true;
  pendingCleanup = null;
});
document.getElementById('applyCleanup').addEventListener('click', async () => {
  const pending = pendingCleanup;
  const editor = document.getElementById('body');
  const status = document.getElementById('cleanupReviewStatus');
  const button = document.getElementById('applyCleanup');
  if (!pending) return;
  if (editor.value !== pending.source) {
    status.textContent = 'The source note changed. Run cleanup again to include your edits.';
    return;
  }
  const proposed = document.getElementById('cleanupText').value.trim();
  if (!proposed) { status.textContent = 'The proposed note is empty. Keep the original or add your notes.'; return; }
  button.disabled = true;
  try {
    status.textContent = 'Saving the original text attachment…';
    const params = new URLSearchParams({session: attachSessionValue(), filename: 'original-note-' + Date.now() + '.txt'});
    const response = await fetch('/api/attachments?' + params, {method: 'POST', body: new Blob([pending.source], {type: 'text/plain;charset=utf-8'})});
    const archive = await response.json();
    if (!response.ok || !archive.ok) throw new Error(archive.error || 'The original could not be saved.');
    if (editor.value !== pending.source) throw new Error('The note changed while the source was being saved. Your edits are still here. Run cleanup again.');
    let result = proposed;
    if (pending.selection) {
      result = pending.source.slice(0, pending.selection.start) + proposed + pending.source.slice(pending.selection.end);
    } else if (pending.data.summary) {
      const positions = ['## Raw Transcript', '## Transcript'].map(marker => pending.source.lastIndexOf(marker));
      const start = Math.max(...positions);
      if (start >= 0) result = pending.source.slice(0, start).trimEnd() + '\n\n' + proposed;
    }
    // Keep image/file attachments visible after replacing a note's prose.
    const attachments = pending.source.match(/!?\[[^\]\n]*\]\(attachments\/[^)\n]+\)/g) || [];
    [...new Set(attachments)].forEach(link => { if (!result.includes(link)) result += '\n\n' + link; });
    editor.value = result.trim() + '\n\n[Original note text](' + archive.path + ')\n';
    const tags = pending.data.summary?.tags || [];
    const field = document.getElementById('tags');
    const existing = field.value.split(',').map(tag => tag.trim()).filter(Boolean);
    tags.forEach(tag => { if (!existing.includes(tag)) existing.push(tag); });
    field.value = existing.join(', ');
    saveDraft();
    refreshSummarizeAvailability();
    refreshAttachGallery();
    document.getElementById('cleanupPreview').hidden = true;
    document.getElementById('statusLine').textContent = 'Reviewed notes applied. Original text attached. Save the note to finish.';
    pendingCleanup = null;
  } catch (error) { status.textContent = error.message || 'Cleanup could not be applied.'; }
  finally { button.disabled = false; }
});
