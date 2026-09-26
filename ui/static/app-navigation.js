(function (root) {
  const safeRoute = route => typeof route === 'string' && route.startsWith('/') && !route.startsWith('//') && !route.startsWith('/api/') && !route.startsWith('/static/');
  function visit(history, route) {
    const pages = Array.isArray(history) ? history.filter(safeRoute) : [];
    if (safeRoute(route) && pages[pages.length - 1] !== route) pages.push(route);
    return pages.slice(-50);
  }
  function recordingMessage(status) {
    if (status.state === 'recording') {
      const seconds = Math.max(0, Math.floor(Number(status.elapsed) || 0));
      const timer = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
      return `Recording · ${timer} — audio capture continues while you use other screens.`;
    }
    if (status.state === 'stopping') return 'Saving your audio. Keep SKATE running.';
    if (status.state === 'transcribing') return `Audio saved. Preparing the final transcript · ${status.progress || 0}%. Keep SKATE running.`;
    if (status.state === 'saved') return 'Audio and transcript saved. Your recording is ready to open.';
    if (status.state === 'error') return status.audio_url ? 'Transcription could not finish. Your saved audio is available in Spotter Live.' : 'Recording needs attention. Open Spotter Live for details.';
    return '';
  }
  if (typeof module !== 'undefined' && module.exports) { module.exports = {visit, recordingMessage}; return; }

  let host;
  try { if (root.parent !== root) host = root.parent.SKATELiveWorkspace; } catch (_) {}
  const key = 'skate-page-history:' + (host ? 'workspace' : 'main');
  let pages = [];
  const save = () => { try { sessionStorage.setItem(key, JSON.stringify(pages)); } catch (_) {} };
  try { pages = JSON.parse(sessionStorage.getItem(key) || '[]'); } catch (_) {}
  // A failed POST still renders the form; never make Back repeat that POST URL.
  const route = location.pathname === '/lineup/new' ? '/lineup' : location.pathname + location.search;
  pages = visit(pages, route);
  save();
  const back = document.querySelector('[data-app-back]');
  if (back) back.addEventListener('click', () => {
    if (root.SKATELiveWorkspace?.returnToWorkspace()) return;
    if (pages.length > 1) {
      pages.pop();
      save();
      root.SKATENavigate(pages[pages.length - 1]);
    } else if (host) host.showLive();
    else root.SKATENavigate('/');
  });

  const banner = document.querySelector('[data-recording-banner]');
  if (!banner || location.pathname === '/spotter-live') return;
  async function updateRecording() {
    try {
      const response = await fetch('/api/recorder/status', {cache: 'no-store'});
      if (!response.ok) throw new Error('Recorder unavailable');
      const status = await response.json();
      const message = recordingMessage(status);
      banner.hidden = !message;
      banner.dataset.state = status.state;
      banner.querySelector('[data-recording-message]').textContent = message;
    } catch (_) {
      if (!banner.hidden) banner.querySelector('[data-recording-message]').textContent = 'Cannot confirm recording status. Return to Spotter Live to check.';
    }
  }
  updateRecording();
  const timer = setInterval(updateRecording, 2000);
  root.addEventListener('pagehide', () => clearInterval(timer), {once: true});
})(typeof window === 'undefined' ? globalThis : window);
