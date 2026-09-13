(() => {
  const dialog = document.getElementById('trashDialog');
  const confirm = document.getElementById('confirmTrash');
  const cancel = document.getElementById('cancelTrash');
  const error = document.getElementById('trashDialogError');
  let selection = null;
  let busy = false;
  document.querySelectorAll('[data-trash-kind]').forEach(button => {
    button.addEventListener('click', () => {
      selection = {...button.dataset};
      const count = Number(selection.trashCount);
      document.getElementById('trashDialogTitle').textContent = selection.trashKind === 'session' ? 'Move this session to Trash?' : 'Move this note to Trash?';
      document.getElementById('trashDialogDescription').textContent = selection.trashKind === 'session'
        ? `“${selection.trashLabel}” and all ${count} ${count === 1 ? 'note' : 'notes'} in this session will be removed from your workspace.`
        : `“${selection.trashLabel}” will be removed from your workspace. Other notes in the session will stay.`;
      error.hidden = true;
      dialog.showModal();
    });
  });
  cancel.addEventListener('click', () => dialog.close());
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  confirm.addEventListener('click', async () => {
    if (!selection || busy) return;
    busy = true;
    confirm.disabled = cancel.disabled = true;
    error.hidden = true;
    try {
      const key = selection.trashKey.split('/').map(encodeURIComponent).join('/');
      const response = await fetch(`/api/trash/${selection.trashKind}/${key}`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({confirmed: true, expected_count: Number(selection.trashCount)})
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || 'Could not move this item to Trash.');
      window.location.assign(result.redirect);
    } catch (problem) {
      error.textContent = problem.message || 'Could not move this item to Trash.';
      error.hidden = false;
    } finally { busy = false; confirm.disabled = cancel.disabled = false; }
  });
  document.querySelectorAll('[data-restore-id]').forEach(button => {
    button.addEventListener('click', async () => {
      const status = document.getElementById('restoreStatus');
      button.disabled = true;
      status.textContent = 'Restoring…';
      status.hidden = false;
      try {
        const response = await fetch(`/api/trash/restore/${encodeURIComponent(button.dataset.restoreId)}`, {method: 'POST'});
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'Could not restore this item.');
        window.location.assign(result.redirect);
      } catch (problem) { status.textContent = problem.message; button.disabled = false; }
    });
  });
})();
