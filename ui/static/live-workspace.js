// Keep the live capture document running while another SKATE screen is open.
(() => {
  const livePath = '/spotter-live';
  let host = null;
  try { if (window.parent !== window) host = window.parent.SKATELiveWorkspace; } catch (_) {}
  const isLiveHost = !host && location.pathname === livePath;
  let panel, frame, returnButton;

  function showLive() {
    if (panel) panel.hidden = true;
    document.querySelectorAll('body > .topbar, body > .shell').forEach(el => { el.inert = false; });
    document.body.style.overflow = '';
    if (returnButton) returnButton.hidden = false;
    window.dispatchEvent(new Event('skate-live-visible'));
  }

  function showPage(url) {
    if (!panel) {
      panel = document.createElement('section');
      panel.className = 'live-workspace-panel';
      frame = document.createElement('iframe');
      try { sessionStorage.removeItem('skate-page-history:workspace'); } catch (_) {}
      frame.title = 'SKATE notes and workspace';
      frame.allow = 'microphone; autoplay';
      panel.append(frame);
      document.body.append(panel);
      returnButton = document.createElement('button');
      returnButton.type = 'button';
      returnButton.className = 'button live-workspace-return';
      returnButton.textContent = 'Return to notes / workspace →';
      returnButton.addEventListener('click', () => showPage());
      document.body.append(returnButton);
    }
    if (url) frame.src = url;
    panel.hidden = false;
    document.querySelectorAll('body > .topbar, body > .shell').forEach(el => { el.inert = true; });
    returnButton.hidden = true;
    document.body.style.overflow = 'hidden';
  }

  window.SKATENavigate = url => {
    const target = new URL(url, location.href);
    if (target.origin !== location.origin) { location.href = target.href; return; }
    if (host && target.pathname === livePath) { host.showLive(); return; }
    if (isLiveHost) {
      if (target.pathname === livePath) showLive();
      else showPage(target.href);
      return;
    }
    location.href = target.href;
  };

  if (isLiveHost) window.SKATELiveWorkspace = {showLive, showPage, returnToWorkspace() {
    if (!panel) return false;
    showPage();
    return true;
  }};
  document.addEventListener('submit', event => {
    if (!isLiveHost || event.defaultPrevented || event.target.method !== 'get') return;
    const target = new URL(event.target.action, location.href);
    if (target.origin !== location.origin) return;
    event.preventDefault();
    target.search = new URLSearchParams(new FormData(event.target)).toString();
    showPage(target.href);
  });
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    if (link.hasAttribute('download') || link.hasAttribute('data-new-note-tab') || (link.target && link.target !== '_self')) return;
    const target = new URL(link.href, location.href);
    if (target.origin !== location.origin || target.pathname.startsWith('/api/') || target.pathname.startsWith('/static/')) return;
    if (target.pathname === location.pathname && target.search === location.search && target.hash) return;
    if (isLiveHost || (host && target.pathname === livePath)) {
      event.preventDefault();
      window.SKATENavigate(target.href);
    }
  });
})();
