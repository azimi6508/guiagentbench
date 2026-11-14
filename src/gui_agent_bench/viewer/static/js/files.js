// Files explorer over allowlisted evidence, and the original-record inspector.
import { api, artifactUrl, text as fetchText } from './api.js';
import { append, button, clear, codeView, empty, h, icon, jsonView, lightbox } from './dom.js';
import { bytes, when } from './format.js';

export async function openRecord(evaluation, path, line, goFiles) {
  const d = document.getElementById('drawer');
  const body = h('div', { class: 'drawer-body' }, h('div', { class: 'muted' }, 'Loading original record…'));
  clear(d).append(h('div', { class: 'drawer-head' }, icon('code'), h('h3', { title: path }, `${path}:${line}`),
    goFiles ? button('Open in Files', () => { d.close(); goFiles(path, line); }, { size: 'sm', icon: 'folder' }) : null,
    button('Close', () => d.close(), { iconOnly: true, icon: 'x', kind: 'ghost' })), body);
  if (!d.open) d.showModal();
  try {
    const record = await api.record(evaluation, path, line);
    append(clear(body), [
      h('div', { class: 'muted small' }, `Source line ${record.line} · byte offset ${record.offset}. Embedded image bytes are replaced by a marker; the original file is unchanged.`),
      record.error ? h('div', { class: 'failure-box' }, icon('alert'), record.error) : null,
      jsonView(record.record, { tall: true })]);
  } catch (error) {
    clear(body).append(empty(error.message));
  }
}

function language(path) {
  if (path.endsWith('.py')) return 'python';
  if (path.endsWith('.json')) return 'json';
  return 'text';
}

function groupByDirectory(artifacts) {
  const groups = new Map();
  for (const a of artifacts) {
    const dir = a.path.includes('/') ? a.path.slice(0, a.path.lastIndexOf('/')) : '';
    if (!groups.has(dir)) groups.set(dir, []);
    groups.get(dir).push(a);
  }
  return [...groups.entries()].sort(([a], [b]) => (a.split('/').length - b.split('/').length) || a.localeCompare(b));
}

export async function renderFiles(root, t) {
  const ev = t.ev;
  const artifacts = ev.artifacts.filter((a) => !a.path.includes('/bridge/images/'));
  const blobs = ev.artifacts.length - artifacts.length;
  let selected = t.route.query.get('path') || (artifacts.find((a) => a.path === 'summary.json') || artifacts[0] || {}).path;
  let focusLine = Number(t.route.query.get('line')) || null;
  const tree = h('nav', { class: 'card tree', 'aria-label': 'Evidence files' });
  const preview = h('div', { class: 'stack' });

  function drawTree() {
    clear(tree);
    for (const [dir, files] of groupByDirectory(artifacts)) {
      tree.append(h('div', { class: 'dir' }, dir ? `${dir}/` : 'evaluation root'));
      for (const f of files.sort((a, b) => a.path.localeCompare(b.path))) {
        tree.append(h('button', { type: 'button', class: f.path === selected ? 'active' : null, title: f.path,
          onclick: () => t.setQuery({ path: f.path, line: null }) },
        icon(f.image ? 'image' : f.path.endsWith('.ndjson') || f.path.endsWith('.log') ? 'list' : 'file'),
        h('span', { class: 'ellipsis' }, f.path.split('/').pop()), h('span', { class: 'sz' }, bytes(f.size))));
      }
    }
    if (blobs) tree.append(h('div', { class: 'dir' }, `+ ${blobs} content-addressed bridge screenshots (shown in the trajectory)`));
  }

  async function drawPreview() {
    clear(preview);
    const file = ev.artifacts.find((a) => a.path === selected);
    if (!file) { preview.append(empty('Select a file. Only allowlisted evidence is served; gold, private, capture and configuration roots are excluded.')); return; }
    const url = artifactUrl(ev.id, file.path);
    preview.append(h('div', { class: 'card card-pad row-between' },
      h('div', null, h('div', { class: 'mono' }, file.path), h('div', { class: 'muted small' }, `${bytes(file.size)} · modified ${when(file.modified)}`)),
      h('a', { class: 'btn btn-sm', href: url, target: '_blank', rel: 'noreferrer' }, icon('external'), 'Raw')));
    const body = h('div');
    preview.append(body);
    if (file.image) {
      body.append(h('div', { class: 'card card-pad' }, h('img', { src: url, alt: file.path, style: { maxWidth: '100%', cursor: 'zoom-in' },
        onclick: () => lightbox.open([{ src: url, caption: file.path }], 0) })));
    } else if (/\.(ndjson|log)$/.test(file.path)) {
      await stream(body, file);
    } else {
      body.append(h('div', { class: 'muted' }, 'Loading…'));
      try {
        const raw = file.size > 2_000_000 ? null : await fetchText(ev.id, file.path);
        clear(body);
        if (raw === null) body.append(empty('This file is larger than 2 MB; open it with Raw. Nothing is truncated on disk.'));
        else if (file.path.endsWith('.json')) {
          let parsed = null;
          try { parsed = JSON.parse(raw); } catch { parsed = null; }
          body.append(parsed !== null ? jsonView(parsed, { tall: true }) : codeView(raw));
        } else body.append(codeView(raw, { lang: language(file.path), tall: true }));
      } catch (error) { clear(body).append(empty(error.message)); }
    }
  }

  async function stream(body, file) {
    let offset = 0;
    const limit = 60;
    const list = h('div', { class: 'card' });
    body.append(list);
    async function page(at) {
      clear(list).append(h('div', { class: 'pager' }, 'Loading records…'));
      let data;
      try { data = await api.events(ev.id, file.path, at, limit); } catch (error) { clear(list).append(empty(error.message)); return null; }
      offset = at;
      clear(list).append(h('div', { class: 'pager' },
        h('span', null, `Records ${data.total ? at + 1 : 0}–${at + data.events.length} of ${data.total} · ${data.order}`),
        h('span', { class: 'row' },
          button('Earlier', () => page(Math.max(0, offset - limit)), { size: 'sm', icon: 'chevronLeft', disabled: at === 0 }),
          button('Later', () => page(data.next), { size: 'sm', icon: 'chevronRight', disabled: data.next === null }))));
      for (const e of data.events) {
        const focus = focusLine && e.revisions.includes(focusLine);
        const title = [e.title, e.status, e.error].filter(Boolean).join(' · ');
        const node = h('div', { class: ['record', focus && 'focus'], id: `rec-${e.line}` }, h('span', { class: 'ln' }, `L${e.revisions[0]}`),
          h('details', { open: focus || null }, h('summary', null, title || e.kind), jsonView(e.record)));
        list.append(node);
      }
      return data;
    }
    let data = await page(0);
    if (focusLine && data) {
      let guard = 0;
      while (data && !data.events.some((e) => e.revisions.includes(focusLine)) && data.next !== null && guard++ < 200) data = await page(data.next);
      const node = list.querySelector('.record.focus');
      if (node) requestAnimationFrame(() => node.scrollIntoView({ block: 'center' }));
    }
  }

  drawTree();
  root.append(h('div', { class: 'files' }, tree, preview));
  await drawPreview();
  return {
    async update(route) {
      selected = route.query.get('path') || selected;
      focusLine = Number(route.query.get('line')) || null;
      drawTree();
      await drawPreview();
    },
  };
}
