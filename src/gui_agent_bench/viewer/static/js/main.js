// Viewer shell: routing, top bar, theme, live polling and global shortcuts.
import { clear, h, icon } from './dom.js';
import { renderRuns } from './runs.js';
import { renderRun } from './run.js';
import { renderEvaluation } from './evaluation.js';

const app = document.getElementById('app');
const POLL_MS = 4000;
let current = null;
let currentKey = null;
let live = localStorage.getItem('gab-live') !== 'off';
let lastPoll = null;
let pollError = false;

export function parseRoute(hash = location.hash) {
  let raw = hash.replace(/^#/, '');
  if (/^(run|evaluation)=/.test(raw) || raw.includes('&evaluation=')) {
    const legacy = new URLSearchParams(raw);
    const tab = { trajectory: 'trajectory', artifacts: 'submission', evaluation: 'execution', inputs: 'task', source: 'files' }[legacy.get('tab')] || '';
    if (legacy.get('evaluation')) raw = `/e/${legacy.get('evaluation')}${tab ? '/' + tab : ''}`;
    else raw = `/run/${legacy.get('run')}`;
  }
  const [path, search] = raw.split('?');
  const query = new URLSearchParams(search || '');
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
  if (parts[0] === 'run' && parts[1] && parts[2] === 'e' && parts[3]) return { page: 'eval', run: parts[1], id: parts[3], tab: parts[4] || 'overview', query };
  if (parts[0] === 'run' && parts[1]) return { page: 'run', run: parts[1], query };
  if (parts[0] === 'e' && parts[1]) return { page: 'eval', run: null, id: parts[1], tab: parts[2] || 'overview', query };
  return { page: 'runs', query };
}

export function href(route) {
  const q = route.query && [...new URLSearchParams(route.query)].length ? `?${new URLSearchParams(route.query)}` : '';
  if (route.page === 'eval') {
    const base = route.run ? `#/run/${encodeURIComponent(route.run)}/e/${encodeURIComponent(route.id)}` : `#/e/${encodeURIComponent(route.id)}`;
    return `${base}${route.tab && route.tab !== 'overview' ? '/' + route.tab : ''}${q}`;
  }
  if (route.page === 'run') return `#/run/${encodeURIComponent(route.run)}${q}`;
  return `#/${q}`;
}

export function navigate(route, opts = {}) {
  const target = href(route);
  if (opts.replace) history.replaceState(null, '', target);
  else history.pushState(null, '', target);
  route_();
}

export function setQuery(changes, opts = { replace: true }) {
  const route = parseRoute();
  for (const [k, v] of Object.entries(changes)) {
    if (v === null || v === undefined || v === '') route.query.delete(k);
    else route.query.set(k, v);
  }
  navigate(route, opts);
}

export function setCrumbs(items) {
  const nav = clear(document.getElementById('crumbs'));
  items.forEach((item, i) => {
    if (i) nav.append(h('span', { class: 'sep' }, '/'));
    nav.append(item.href && i < items.length - 1 ? h('a', { href: item.href, title: item.title || item.label }, item.label)
      : h('span', { class: i === items.length - 1 ? 'current' : null, title: item.title || item.label }, item.label));
  });
  document.title = `${items.length ? items[items.length - 1].label + ' · ' : ''}GUIAgentBench viewer`;
}

const ctx = { navigate, setQuery, href, setCrumbs, parseRoute };

async function route_() {
  const route = parseRoute();
  const key = route.page === 'eval' ? `eval:${route.id}` : route.page === 'run' ? `run:${route.run}` : 'runs';
  try {
    if (current && currentKey === key && current.update) {
      await current.update(route);
      return;
    }
    if (current && current.dispose) current.dispose();
    currentKey = key;
    clear(app).append(h('div', { class: 'page-loading' }, 'Reading recorded evidence…'));
    const render = route.page === 'eval' ? renderEvaluation : route.page === 'run' ? renderRun : renderRuns;
    current = await render(app, route, ctx);
    if (route.page !== 'eval' || !route.query.get('step')) window.scrollTo(0, 0);
  } catch (error) {
    current = null;
    currentKey = null;
    clear(app).append(h('div', { class: 'page-error' }, h('h2', null, error.status === 404 ? 'Not found' : 'Could not open this view'),
      h('p', null, error.message || String(error)), h('a', { href: '#/' }, 'Back to all runs')));
    console.error(error);
  }
}

function setLiveState() {
  const state = document.getElementById('live-state');
  clear(state);
  state.className = `live-state ${live ? (pollError ? 'error' : 'on') : ''}`;
  state.append(h('span', { class: 'dot' }), live ? (pollError ? 'Connection lost' : lastPoll ? `Live · ${lastPoll.toLocaleTimeString()}` : 'Live') : 'Paused');
  const toggle = document.getElementById('live-toggle');
  toggle.setAttribute('aria-pressed', String(live));
  toggle.textContent = live ? 'Pause' : 'Resume';
}

async function poll(force = false) {
  if (!current || !current.poll) return;
  if (!force && (!live || document.visibilityState !== 'visible')) return;
  try {
    await current.poll();
    pollError = false;
    lastPoll = new Date();
  } catch (error) {
    pollError = true;
  }
  setLiveState();
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const button = clear(document.getElementById('theme'));
  button.append(icon(theme === 'dark' ? 'sun' : 'moon'));
}

function shortcuts() {
  const d = document.getElementById('shortcuts');
  clear(d).append(h('div', { class: 'drawer-head' }, h('h3', null, 'Keyboard shortcuts'),
    h('button', { class: 'btn btn-ghost btn-icon', type: 'button', onclick: () => d.close(), 'aria-label': 'Close' }, icon('x'))),
  h('div', { class: 'drawer-body' }, h('div', { class: 'shortcuts' },
    ...[['?', 'Show this help'], ['r', 'Refresh evidence now'], ['/', 'Focus search or filter'],
      ['1 – 6', 'Switch evaluation tabs'], ['[  ]', 'Previous / next evaluation in the run'],
      ['j  k', 'Next / previous trajectory step'], ['n  p', 'Next / previous problem step'],
      ['← →', 'Previous / next image in the viewer'], ['0', 'Toggle actual image size'], ['Esc', 'Close dialogs']]
      .flatMap(([k, v]) => [h('span', null, ...k.split(/\s{2}/).map((x) => h('kbd', null, x))), h('span', null, v)]))));
  d.showModal();
}

function init() {
  const stored = localStorage.getItem('gab-theme');
  applyTheme(stored || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
  document.getElementById('theme').addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('gab-theme', next);
    applyTheme(next);
  });
  document.getElementById('refresh').append(icon('refresh'));
  document.getElementById('refresh').addEventListener('click', () => poll(true));
  document.getElementById('help').append(icon('help'));
  document.getElementById('help').addEventListener('click', shortcuts);
  document.getElementById('live-toggle').addEventListener('click', () => {
    live = !live;
    localStorage.setItem('gab-live', live ? 'on' : 'off');
    setLiveState();
    if (live) poll(true);
  });
  window.addEventListener('hashchange', route_);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') poll(); });
  document.addEventListener('keydown', (e) => {
    if (e.target.closest('input, textarea, select') || e.metaKey || e.ctrlKey || e.altKey) return;
    if (document.querySelector('dialog[open]') && e.key !== 'Escape') return;
    // Enter and Space belong to the focused link, button or row; page shortcuts must not hijack them.
    if ((e.key === 'Enter' || e.key === ' ') && e.target.closest('a, button, summary, [role="button"], [tabindex]')) return;
    if (e.key === '?') { e.preventDefault(); shortcuts(); }
    else if (e.key === 'r') { e.preventDefault(); poll(true); }
    else if (e.key === '/') {
      const search = app.querySelector('input[type="search"]');
      if (search) { e.preventDefault(); search.focus(); }
    } else if (current && current.key) current.key(e);
  });
  setInterval(poll, POLL_MS);
  setLiveState();
  route_();
}

init();
