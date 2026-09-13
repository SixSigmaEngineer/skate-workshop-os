(() => {
  const picker = document.getElementById('themePicker');
  if (!picker) return;
  const root = document.documentElement;
  picker.querySelectorAll('[data-theme-choice]').forEach(button => {
    button.addEventListener('click', () => {
      const theme = JSON.parse(button.dataset.themeChoice);
      root.dataset.uiTheme = theme.id;
      root.dataset.uiDark = String(theme.dark);
      Object.entries(theme.colors).forEach(([key, value]) => root.style.setProperty('--' + key, value));
      document.getElementById('uiTheme').value = theme.id;
      document.getElementById('themeName').textContent = theme.label;
      document.getElementById('themeImage').src = theme.image;
      document.getElementById('themeImage').alt = theme.label + ' skateboard';
      picker.querySelectorAll('[data-theme-choice]').forEach(other => other.setAttribute('aria-pressed', String(other === button)));
      picker.open = false;
      picker.querySelector('summary').focus();
    });
  });
  picker.addEventListener('keydown', event => {
    if (event.key === 'Escape') { picker.open = false; picker.querySelector('summary').focus(); }
  });
  document.getElementById('openThemeFolder').addEventListener('click', async () => {
    const status = document.getElementById('themeFolderStatus');
    try {
      const response = await fetch('/api/theme-boards/open', {method: 'POST'});
      const data = await response.json();
      status.textContent = data.ok ? 'Board folder: ' + data.path : data.error;
    } catch (_) { status.textContent = 'The folder could not be opened.'; }
  });
})();
