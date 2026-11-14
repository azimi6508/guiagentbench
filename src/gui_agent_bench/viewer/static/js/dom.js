// DOM construction helpers and shared components. Text always goes through
// text nodes; recorded content is never interpreted as HTML.
import { OUTCOMES, parseInline, parseMarkdown, tokenizeJson, tokenizePython } from './format.js';

const SVG = 'http://www.w3.org/2000/svg';

export function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = Array.isArray(value) ? value.filter(Boolean).join(' ') : value;
      else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
      else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
      else if (key === 'dataset') Object.assign(node.dataset, value);
      else if (value === true) node.setAttribute(key, '');
      else node.setAttribute(key, String(value));
    }
  }
  append(node, children);
  return node;
}

// Attributes that make a non-native control reachable and operable from the keyboard.
export function activate(handler) {
  return { tabindex: '0', onclick: handler,
    onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); handler(e); } } };
}

export function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

const ICONS = {
  check: [['p', 'M20 6 9 17l-5-5']],
  x: [['p', 'M18 6 6 18M6 6l12 12']],
  alert: [['p', 'M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01']],
  info: [['c', 12, 12, 10], ['p', 'M12 16v-4M12 8h.01']],
  clock: [['c', 12, 12, 10], ['p', 'M12 6v6l4 2']],
  pointer: [['p', 'M4 3l7 17 2.5-7.4L21 10z']],
  keyboard: [['r', 2, 6, 20, 12, 2], ['p', 'M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10']],
  globe: [['c', 12, 12, 10], ['p', 'M2 12h20M12 2a15 15 0 0 1 4 10 15 15 0 0 1-4 10 15 15 0 0 1-4-10 15 15 0 0 1 4-10z']],
  rotate: [['p', 'M3 12a9 9 0 1 0 3-6.7L3 8'], ['p', 'M3 3v5h5']],
  refresh: [['p', 'M21 12a9 9 0 1 1-3-6.7L21 8'], ['p', 'M21 3v5h-5']],
  camera: [['p', 'M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z'], ['c', 12, 13, 4]],
  file: [['p', 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'], ['p', 'M14 2v6h6']],
  pen: [['p', 'M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z']],
  list: [['p', 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01']],
  tree: [['r', 3, 3, 6, 6, 1], ['r', 15, 15, 6, 6, 1], ['p', 'M6 9v6a3 3 0 0 0 3 3h6']],
  message: [['p', 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z']],
  sparkle: [['p', 'M12 3l1.9 5.8L20 10l-6.1 1.2L12 17l-1.9-5.8L4 10l6.1-1.2z']],
  user: [['c', 12, 7, 4], ['p', 'M5.5 21a6.5 6.5 0 0 1 13 0']],
  shield: [['p', 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'], ['p', 'M9.5 9.5l5 5M14.5 9.5l-5 5']],
  stop: [['p', 'M7.9 2h8.2L22 7.9v8.2L16.1 22H7.9L2 16.1V7.9z'], ['p', 'M15 9l-6 6M9 9l6 6']],
  flag: [['p', 'M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1zM4 22v-7']],
  terminal: [['p', 'M4 17l6-6-6-6M12 19h8']],
  search: [['c', 11, 11, 7], ['p', 'M21 21l-4.3-4.3']],
  chevronRight: [['p', 'M9 18l6-6-6-6']],
  chevronLeft: [['p', 'M15 18l-6-6 6-6']],
  chevronDown: [['p', 'M6 9l6 6 6-6']],
  sun: [['c', 12, 12, 4], ['p', 'M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4']],
  moon: [['p', 'M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z']],
  help: [['c', 12, 12, 10], ['p', 'M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01']],
  external: [['p', 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3']],
  code: [['p', 'M16 18l6-6-6-6M8 6l-6 6 6 6']],
  image: [['r', 3, 3, 18, 18, 2], ['c', 8.5, 8.5, 1.5], ['p', 'M21 15l-5-5L5 21']],
  eye: [['p', 'M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z'], ['c', 12, 12, 3]],
  folder: [['p', 'M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z']],
  layers: [['p', 'M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5']],
  target: [['c', 12, 12, 10], ['c', 12, 12, 6], ['c', 12, 12, 2]],
  beaker: [['p', 'M9 3h6M10 3v6L4.5 19a2 2 0 0 0 1.8 3h11.4a2 2 0 0 0 1.8-3L14 9V3']],
  box: [['p', 'M21 16V8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4a2 2 0 0 0 1-1.7z'], ['p', 'M3.3 7 12 12l8.7-5M12 22V12']],
  minus: [['p', 'M5 12h14']],
  hash: [['p', 'M4 9h16M4 15h16M10 3 8 21M16 3l-2 18']],
  play: [['p', 'M6 4l14 8-14 8z']],
  zoom: [['c', 11, 11, 7], ['p', 'M21 21l-4.3-4.3M11 8v6M8 11h6']],
  link: [['p', 'M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7']],
  shieldCheck: [['p', 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'], ['p', 'M9 12l2 2 4-4']],
};

export function icon(name, cls) {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('class', cls || 'icon');
  for (const [kind, ...v] of ICONS[name] || ICONS.info) {
    const el = document.createElementNS(SVG, kind === 'p' ? 'path' : kind === 'c' ? 'circle' : 'rect');
    if (kind === 'p') el.setAttribute('d', v[0]);
    else if (kind === 'c') { el.setAttribute('cx', v[0]); el.setAttribute('cy', v[1]); el.setAttribute('r', v[2]); }
    else { el.setAttribute('x', v[0]); el.setAttribute('y', v[1]); el.setAttribute('width', v[2]); el.setAttribute('height', v[3]); el.setAttribute('rx', v[4]); }
    svg.append(el);
  }
  return svg;
}

export const OUTCOME_ICONS = { credited: 'check', zero: 'x', error: 'alert', interrupted: 'stop', running: 'clock', unpaired: 'minus', unresolved: 'minus', missing: 'minus' };

export function outcomeBadge(outcome, label, extra) {
  const o = OUTCOMES[outcome] || OUTCOMES.unresolved;
  return h('span', { class: ['badge', outcome, extra], title: o.description }, icon(OUTCOME_ICONS[outcome] || 'minus'), label || o.label);
}

export function badge(text, tone, iconName, title) {
  return h('span', { class: ['badge', tone], title }, iconName ? icon(iconName) : null, text);
}

export function chip(text, key, opts = {}) {
  return h('span', { class: ['chip', opts.mono && 'mono'], title: opts.title || null }, opts.icon ? icon(opts.icon) : null,
    key ? h('span', { class: 'k' }, key) : null, text);
}

export function button(label, onclick, opts = {}) {
  return h('button', { type: 'button', class: ['btn', opts.kind && `btn-${opts.kind}`, opts.size && `btn-${opts.size}`, opts.iconOnly && 'btn-icon'],
    onclick, title: opts.title, disabled: opts.disabled, 'aria-label': opts.iconOnly ? label : null },
  opts.icon ? icon(opts.icon) : null, opts.iconOnly ? null : label);
}

export function linkButton(label, href, opts = {}) {
  return h('a', { class: ['btn', opts.kind && `btn-${opts.kind}`, opts.size && `btn-${opts.size}`], href, title: opts.title },
    opts.icon ? icon(opts.icon) : null, label);
}

export function segmented(options, value, onchange) {
  return h('div', { class: 'segmented', role: 'group' }, options.map((o) => h('button', {
    type: 'button', 'aria-pressed': String(o.value === value), onclick: () => onchange(o.value), title: o.title,
  }, o.icon ? icon(o.icon) : null, o.label, o.count !== undefined ? h('span', { class: 'count' }, o.count) : null)));
}

export function callout(tone, iconName, ...children) {
  return h('div', { class: ['callout', tone] }, icon(iconName), h('div', { class: 'grow' }, ...children));
}

export function empty(text) { return h('div', { class: 'empty' }, text); }

export function kv(pairs) {
  const dl = h('dl', { class: 'kv' });
  for (const [key, value, mono] of pairs) {
    if (value === undefined) continue;
    dl.append(h('dt', null, key), h('dd', { class: mono ? 'mono' : null }, value === null || value === '' ? '—' : value));
  }
  return dl;
}

export function card(title, body, opts = {}) {
  return h('section', { class: ['card', opts.class] },
    title ? h('div', { class: 'card-head' }, h('h3', null, opts.icon ? icon(opts.icon) : null, title), opts.actions || null) : null,
    h('div', { class: opts.flush ? null : 'card-body' }, body),
    opts.foot ? h('div', { class: 'card-foot' }, opts.foot) : null);
}

function tokens(list) {
  return list.map(([type, text]) => (type ? h('span', { class: `tok-${type}` }, text) : document.createTextNode(text)));
}

// Code viewer with line numbers. `highlight` maps line number -> 'hl' | 'note'.
export function codeView(text, opts = {}) {
  const lines = String(text ?? '').replace(/\n$/, '').split('\n');
  const start = opts.firstLine || 1;
  const highlight = opts.highlight || {};
  const lang = opts.lang || 'text';
  const table = h('table');
  lines.forEach((line, i) => {
    const n = start + i;
    const content = lang === 'python' ? tokens(tokenizePython(line)) : lang === 'json' ? tokens(tokenizeJson(line)) : [line];
    table.append(h('tr', { class: highlight[n] || null, id: opts.idPrefix ? `${opts.idPrefix}${n}` : null, title: opts.titles?.[n] || null },
      h('td', { class: 'ln' }, n), h('td', null, content.length ? content : ' ')));
  });
  const box = h('div', { class: ['code', opts.tall && 'tall'] }, table);
  if (!opts.title && !opts.actions) return box;
  return h('div', null, h('div', { class: 'code-head' }, h('span', { class: 'mono' }, opts.title || ''), h('span', { class: 'row' }, opts.actions || null)), box);
}

export function preView(text, opts = {}) {
  return h('div', { class: ['code', opts.wrap !== false && 'wrap', opts.tall && 'tall'] }, h('pre', null, text));
}

export function jsonView(value, opts = {}) {
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  return h('div', { class: ['code', opts.tall && 'tall'] }, h('pre', { class: 'json' }, tokens(tokenizeJson(text ?? 'null'))));
}

export function markdown(text) {
  const root = h('div', { class: 'md' });
  const inline = (s) => parseInline(s).map(([type, a, b]) => {
    if (type === 'code') return h('code', null, a);
    if (type === 'strong') return h('strong', null, a);
    if (type === 'em') return h('em', null, a);
    if (type === 'link') return h('span', { class: 'link', title: b }, a);
    return document.createTextNode(a);
  });
  for (const block of parseMarkdown(text)) {
    if (block.type === 'heading') root.append(h(`h${Math.min(4, block.level + 1)}`, null, inline(block.text)));
    else if (block.type === 'code') root.append(h('pre', null, h('code', null, block.text)));
    else if (block.type === 'ul' || block.type === 'ol') root.append(h(block.type, null, block.items.map((i) => h('li', null, inline(i)))));
    else root.append(h('p', null, inline(block.text)));
  }
  return root;
}

// Collapsible long text: never truncates the evidence, only the initial display.
export function longText(text, opts = {}) {
  const limit = opts.lines || 18;
  const lines = String(text ?? '').split('\n');
  const view = opts.code ? (t) => codeView(t, opts) : (t) => preView(t, opts);
  if (lines.length <= limit + 4) return view(text);
  const holder = h('div', { class: 'stack' });
  let expanded = false;
  const render = () => {
    clear(holder);
    holder.append(view(expanded ? text : lines.slice(0, limit).join('\n')),
      h('button', { type: 'button', class: 'collapse-toggle', onclick: () => { expanded = !expanded; render(); } },
        expanded ? 'Show fewer lines' : `Show all ${lines.length} lines`));
  };
  render();
  return holder;
}

// ---------- screenshots ----------
export function shot(src, opts = {}) {
  const frame = h('div', { class: ['shot', opts.small && 'small'], role: 'button', tabindex: '0', title: opts.title || 'Open full size' });
  const img = h('img', { src, alt: opts.alt || 'Recorded screenshot', loading: 'lazy', decoding: 'async' });
  frame.append(img);
  const place = () => {
    for (const m of frame.querySelectorAll('.marker, .region-box')) m.remove();
    const width = img.naturalWidth || opts.width;
    const height = img.naturalHeight || opts.height;
    if (!width || !height) return;
    if (opts.point) {
      frame.append(h('span', { class: 'marker', style: { left: `${(opts.point[0] / width) * 100}%`, top: `${(opts.point[1] / height) * 100}%` } }));
    }
    if (opts.region) {
      const [x1, y1, x2, y2] = opts.region;
      frame.append(h('span', { class: 'region-box', style: { left: `${(x1 / width) * 100}%`, top: `${(y1 / height) * 100}%`,
        width: `${((x2 - x1) / width) * 100}%`, height: `${((y2 - y1) / height) * 100}%` } }));
    }
  };
  img.addEventListener('load', place);
  if (opts.caption) frame.append(h('span', { class: 'cap' }, opts.caption));
  const open = () => (opts.onopen ? opts.onopen() : lightbox.open([{ src, caption: opts.caption || opts.alt, point: opts.point, region: opts.region }], 0));
  frame.addEventListener('click', open);
  frame.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
  return frame;
}

// ---------- lightbox ----------
export const lightbox = (() => {
  let items = [];
  let index = 0;
  let actual = false;
  const dialog = () => document.getElementById('lightbox');
  function render() {
    const d = dialog();
    clear(d);
    const item = items[index];
    if (!item) return;
    const img = h('img', { src: item.src, alt: item.caption || 'Screenshot' });
    const frame = h('div', { class: 'lb-frame' }, img);
    img.addEventListener('load', () => {
      const w = img.naturalWidth;
      const hh = img.naturalHeight;
      if (item.point) frame.append(h('span', { class: 'marker', style: { left: `${(item.point[0] / w) * 100}%`, top: `${(item.point[1] / hh) * 100}%` } }));
      if (item.region) {
        const [x1, y1, x2, y2] = item.region;
        frame.append(h('span', { class: 'region-box', style: { left: `${(x1 / w) * 100}%`, top: `${(y1 / hh) * 100}%`, width: `${((x2 - x1) / w) * 100}%`, height: `${((y2 - y1) / hh) * 100}%` } }));
      }
      dims.textContent = `${w}×${hh}`;
    });
    const dims = h('span', { class: 'mono small' });
    d.append(
      h('div', { class: 'lb-bar' },
        h('span', { class: 'mono small' }, `${index + 1} / ${items.length}`),
        h('span', { class: 'cap' }, item.caption || ''),
        dims,
        button(actual ? 'Fit to screen' : 'Actual size', () => { actual = !actual; render(); }, { size: 'sm', icon: 'zoom' }),
        h('a', { class: 'btn btn-sm', href: item.src, target: '_blank', rel: 'noreferrer' }, icon('external'), 'Original'),
        button('Previous', () => go(-1), { size: 'sm', icon: 'chevronLeft', iconOnly: true, disabled: index === 0 }),
        button('Next', () => go(1), { size: 'sm', icon: 'chevronRight', iconOnly: true, disabled: index >= items.length - 1 }),
        button('Close', () => d.close(), { size: 'sm', icon: 'x', iconOnly: true })),
      h('div', { class: ['lb-stage', actual && 'actual'], onclick: (e) => { if (e.target === e.currentTarget) d.close(); } }, frame));
  }
  function go(delta) { index = Math.max(0, Math.min(items.length - 1, index + delta)); render(); }
  function open(list, start = 0) {
    items = list; index = start; actual = false;
    render();
    if (!dialog().open) dialog().showModal();
  }
  document.addEventListener('keydown', (e) => {
    if (!dialog() || !dialog().open) return;
    if (e.key === 'ArrowRight') { e.preventDefault(); go(1); }
    if (e.key === 'ArrowLeft') { e.preventDefault(); go(-1); }
    if (e.key === '0') { actual = !actual; render(); }
  });
  return { open };
})();

export function toast(text, action) {
  const old = document.querySelector('.banner');
  if (old) old.remove();
  const node = h('div', { class: 'banner', role: 'status' }, text, action || null);
  document.body.append(node);
  setTimeout(() => node.remove(), 4000);
}
