/* Info-only controls for the site's bundled board. No continuous render loop. */
(() => {
  'use strict';
  const park = document.querySelector('.about-skatepark');
  if (!park) return;
  const revealBenchmark = () => {
    if (window.location.hash === '#retrieval-benchmark') {
      const detail = document.getElementById('retrieval-benchmark');
      if (detail) detail.open = true;
    }
  };
  window.addEventListener('hashchange', revealBenchmark);
  revealBenchmark();
  const stage = park.querySelector('.park-stage');
  const board = park.querySelector('.rail-board');
  const shadow = park.querySelector('.park-shadow');
  const controls = park.querySelector('.park-controls');
  const toggle = park.querySelector('[data-motion-toggle]');
  const status = park.querySelector('.park-status');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const preferenceKey = 'skate-about-board-paused';
  let paused = reduced.matches;
  try { paused = paused || localStorage.getItem(preferenceKey) === 'true'; } catch (_) {}
  let inView = false;
  let assetRequested = false;
  let timer = 0;
  let frame = 0;
  let flight = null;
  let stop = 1;
  let nextTrick = 'ollie';

  function paint(position = stop, lift = 0, pitch = 0, flip = 0) {
    const width = board.offsetWidth;
    const x = 8 + Math.max(0, stage.clientWidth - width - 16) * position / 2;
    const model = window.SKATEBoard3D;
    const anchor = model?.ready ? model.anchor : 0.75;
    const floor = stage.clientHeight - 36;
    const y = floor - board.offsetHeight * anchor - lift;
    board.style.transform = `translate3d(${x}px, ${y}px, 0) rotate(${pitch}deg)`;
    shadow.style.transform = `translateX(${x + width * 0.1}px) scale(${1 - lift / 180})`;
    shadow.style.width = `${width * 0.8}px`;
    shadow.style.opacity = String(0.24 - lift / 500);
    if (model?.ready) model.setHop(flip);
    else board.querySelector('img').style.transform = `rotateX(${flip * 360}deg)`;
  }

  function clearSchedule() {
    window.clearTimeout(timer);
    window.cancelAnimationFrame(frame);
    timer = frame = 0;
  }

  function queueNext() {
    window.clearTimeout(timer);
    timer = 0;
    if (paused || !inView || document.hidden || flight) return;
    timer = window.setTimeout(() => {
      timer = 0;
      jump(nextTrick);
      nextTrick = nextTrick === 'ollie' ? 'kickflip' : 'ollie';
    }, 5500);
  }

  function settle() {
    clearSchedule();
    if (flight) stop = flight.to;
    flight = null;
    paint();
    queueNext();
  }

  function tick(now) {
    frame = 0;
    if (!flight || !inView || document.hidden) return settle();
    if (flight.started === null) flight.started = now;
    const t = Math.min(1, (now - flight.started) / 1050);
    const ease = t * t * (3 - 2 * t);
    const lift = Math.sin(Math.PI * t) * 66;
    paint(flight.from + (flight.to - flight.from) * ease, lift,
      -Math.sin(t * Math.PI * 2) * 12, flight.trick === 'kickflip' ? t : 0);
    if (t < 1) frame = window.requestAnimationFrame(tick);
    else {
      const announce = flight.manual;
      const trick = flight.trick;
      stop = flight.to;
      flight = null;
      paint();
      if (announce) status.textContent = `${trick === 'kickflip' ? 'Kickflip' : 'Ollie'} landed.`;
      queueNext();
    }
  }

  function jump(trick, manual = false) {
    clearSchedule();
    if (flight) stop = flight.to;
    const target = stop === 2 ? 0 : stop + 1;
    flight = {from: stop, to: target, started: null, trick, manual};
    if (!inView || document.hidden) return settle();
    if (manual) status.textContent = trick === 'kickflip' ? 'Kickflip…' : 'Ollie…';
    frame = window.requestAnimationFrame(tick);
  }

  function updateControls() {
    toggle.textContent = paused ? 'Play motion' : 'Pause motion';
    toggle.setAttribute('aria-label', paused ? 'Play automatic board motion' : 'Pause automatic board motion');
  }

  function requestModel() {
    if (assetRequested) return;
    assetRequested = true;
    const script = document.createElement('script');
    script.src = park.dataset.boardScript;
    script.async = true;
    script.onerror = () => { status.textContent = 'Board artwork mode. You can still ride.'; };
    document.head.append(script);
  }

  controls.hidden = false;
  controls.querySelectorAll('[data-trick]').forEach(button => {
    button.addEventListener('click', () => jump(button.dataset.trick, true));
  });
  toggle.addEventListener('click', () => {
    paused = !paused;
    try { localStorage.setItem(preferenceKey, String(paused)); } catch (_) {}
    updateControls();
    settle();
    status.textContent = paused ? 'Motion paused. Tricks still work when you choose one.' : 'Ready to ride. Select a trick or watch the board.';
  });
  reduced.addEventListener('change', () => {
    if (reduced.matches) {
      paused = true;
      updateControls();
      settle();
      status.textContent = 'Motion paused for your reduced-motion preference.';
    }
  });
  board.addEventListener('skateboardready', settle);
  new ResizeObserver(settle).observe(stage);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) settle();
    else queueNext();
  });
  window.addEventListener('pagehide', () => { inView = false; settle(); });
  window.addEventListener('pageshow', () => {
    const bounds = stage.getBoundingClientRect();
    inView = bounds.bottom > 0 && bounds.top < window.innerHeight;
    if (inView) requestModel();
    queueNext();
  });
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(([entry]) => {
      inView = entry.isIntersecting;
      if (inView) { requestModel(); queueNext(); }
      else settle();
    }, {threshold: 0.1}).observe(stage);
  } else {
    inView = true;
    requestModel();
    queueNext();
  }
  updateControls();
  paint();
  status.textContent = paused ? 'Motion paused. Choose a trick when you want some airtime.' : 'Select a trick or watch the board find its line.';
})();
