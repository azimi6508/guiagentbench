// Runner-neutral trajectory: Codex and OpenCode steps in one readable feed.
import { api, imageUrl } from './api.js';
import { append, badge, chip, clear, codeView, empty, h, icon, lightbox, longText, markdown, segmented, shot } from './dom.js';
import { RUNNER_LABELS, bytes, causeHint, clock, compact, duration, formatNumber, human, stepMatches } from './format.js';

const cache = new Map();

export async function loadTrajectory(evaluation, trial) {
  const key = `${evaluation}:${trial}`;
  if (!cache.has(key)) cache.set(key, api.trajectory(evaluation, trial).catch((e) => { cache.delete(key); throw e; }));
  return cache.get(key);
}

export function clearTrajectories(evaluation) {
  for (const key of [...cache.keys()]) if (key.startsWith(`${evaluation}:`)) cache.delete(key);
}

const ACTION_ICONS = { click: 'pointer', tap: 'pointer', double_click: 'pointer', long_press: 'pointer', hover: 'pointer', type: 'keyboard',
  type_text: 'keyboard', fill: 'keyboard', press: 'keyboard', key: 'keyboard', scroll: 'chevronDown', reload: 'rotate', evaluate: 'code' };
const TOOL_ICONS = { gui_observe: 'camera', bench_read_image: 'image', gui_dump_ui: 'tree', gui_reset: 'rotate', gui_open_url: 'globe',
  bench_list_files: 'folder', list: 'folder', bench_read_file: 'file', read: 'file', bench_write_file: 'pen', write: 'pen', edit: 'pen', bash: 'terminal' };
const KIND_ICONS = { prompt: 'user', message: 'message', reasoning: 'sparkle', blocked: 'shield', interrupt: 'stop', error: 'alert', end: 'flag', notice: 'info' };

export function stepIcon(step) {
  if (step.kind === 'tool') {
    if (step.tool === 'gui_step') return ACTION_ICONS[step.arguments?.action] || 'pointer';
    return TOOL_ICONS[step.tool] || 'code';
  }
  return KIND_ICONS[step.kind] || 'info';
}

function language(path) {
  if (!path) return 'text';
  if (path.endsWith('.py')) return 'python';
  if (path.endsWith('.json')) return 'json';
  return 'text';
}

export async function renderTrajectory(root, t) {
  const ev = t.ev;
  const trials = ev.trials.filter((x) => x.trajectory?.available);
  if (!trials.length) {
    root.append(empty(ev.kind === 'reference' ? 'No agent trajectory: the reference controller bypassed the evaluated agent.'
      : ev.outcome === 'running' ? 'No agent trajectory has been recorded yet. Live updates will show it as soon as the runner writes it.'
        : 'No agent trajectory was recorded for this evaluation.'));
    return {};
  }
  let state = read(t.route);
  let traj = null;
  let activeIndex = null;

  function read(route) {
    const trial = trials.find((x) => x.id === route.query.get('trial')) || trials[0];
    return { trial, filter: route.query.get('filter') || 'all', q: route.query.get('q') || '',
      notices: route.query.get('notices') === '1', targets: route.query.get('targets') !== '0', step: Number(route.query.get('step')) || null };
  }

  async function draw() {
    clear(root).append(h('div', { class: 'page-loading' }, 'Loading trajectory…'));
    try {
      traj = await loadTrajectory(ev.id, state.trial.id);
    } catch (error) {
      clear(root).append(empty(error.message));
      return;
    }
    clear(root).append(toolbar(), summary(), filmstrip(), body());
    if (state.step) requestAnimationFrame(() => focus(state.step, 'instant'));
  }

  function routine(s) { return s.minor || (s.kind === 'reasoning' && s.hidden); }

  function visibleSteps() {
    return traj.steps.filter((s) => (state.notices || !routine(s)) && stepMatches(s, state.filter, state.q));
  }

  function toolbar() {
    const steps = traj.steps.filter((s) => state.notices || !routine(s));
    const hiddenCount = traj.steps.length - steps.length;
    const countOf = (f) => steps.filter((s) => stepMatches(s, f, '')).length;
    const trialSwitch = trials.length > 1 ? segmented(trials.map((x) => ({
      value: x.id, label: ev.arm.family === 'judge' ? (x.variant === 'faulty' ? 'Faulty state' : 'Correct state') : x.variant,
      title: `Trial ${x.id}`, count: x.trajectory?.stats?.steps,
    })), state.trial.id, (v) => t.setQuery({ trial: v, step: null })) : null;
    return h('div', { class: 'traj-toolbar' },
      trialSwitch,
      segmented([
        { value: 'all', label: 'All', count: steps.length }, { value: 'actions', label: 'Tool calls', count: countOf('actions') },
        { value: 'messages', label: 'Messages', count: countOf('messages') }, { value: 'problems', label: 'Problems', count: countOf('problems'), icon: 'alert' },
        { value: 'screens', label: 'Screenshots', count: countOf('screens'), icon: 'camera' },
      ], state.filter, (v) => t.setQuery({ filter: v === 'all' ? null : v })),
      h('input', { type: 'search', placeholder: 'Search steps, arguments, outputs…', value: state.q, 'aria-label': 'Search trajectory',
        oninput: (e) => t.setQuery({ q: e.target.value || null }) }),
      h('span', { class: 'spacer' }),
      h('label', { class: 'toggle', title: 'Show the last screenshot before each coordinate action with the target marked' },
        h('input', { type: 'checkbox', checked: state.targets || null, onchange: (e) => t.setQuery({ targets: e.target.checked ? null : '0' }) }), 'Click targets'),
      !hiddenCount && !state.notices ? null : h('label', { class: 'toggle', title: 'Runner startup warnings and reasoning items whose content the provider did not expose' },
        h('input', { type: 'checkbox', checked: state.notices || null, onchange: (e) => t.setQuery({ notices: e.target.checked ? '1' : null }) }),
        state.notices ? 'Routine records shown' : `Show ${hiddenCount} routine records`));
  }

  function summary() {
    const s = traj.stats;
    const tk = s.tokens || {};
    const end = traj.end || {};
    const cats = Object.entries(s.by_category || {}).map(([k, v]) => `${v} ${k}`).join(', ');
    const items = [
      ['Runner', `${RUNNER_LABELS[traj.runner] || traj.runner}${traj.info?.cli_version ? ' ' + traj.info.cli_version : ''}`],
      traj.info?.model ? ['Model', `${traj.info.model}${traj.info.reasoning_effort ? ' · ' + traj.info.reasoning_effort : ''}`] : null,
      ['Duration', duration(s.duration_ms)],
      ['Tool calls', `${formatNumber(s.tool_calls)}${cats ? ` (${cats})` : ''}`],
      ['Failed / blocked', formatNumber((s.failed_tools || 0) + (s.blocked || 0))],
      ['Screenshots', formatNumber(s.screenshots)],
      tk.input !== undefined ? ['Tokens', `${compact(tk.input)} in${tk.cached_input ? ` (${compact(tk.cached_input)} cached)` : ''} · ${compact(tk.output)} out${tk.reasoning ? ` · ${compact(tk.reasoning)} reasoning` : ''}`] : null,
      ['Ended', end.status ? human(end.status) : '—'],
    ].filter(Boolean);
    return h('div', { class: 'card' },
      h('div', { class: 'traj-summary' }, items.map(([k, v]) => h('span', null, `${k}: `, h('b', null, v)))),
      (traj.warnings || []).length ? h('div', { style: { padding: '0 14px 10px' } }, traj.warnings.map((w) => h('div', { class: 'muted small' }, icon('info'), ' ', w))) : null);
  }

  function screenshots() {
    const out = [];
    for (const step of traj.steps) {
      (step.images || []).forEach((image, i) => out.push({ step, image, i }));
    }
    return out;
  }

  function filmstrip() {
    const list = screenshots();
    if (!list.length) return h('div', { style: { height: '12px' } });
    const strip = h('div', { class: 'card filmstrip', 'aria-label': 'All screenshots in this trajectory' });
    list.forEach(({ step, image }, n) => {
      strip.append(h('button', { type: 'button', dataset: { step: step.index }, title: `Step ${step.index}: ${step.title}`,
        onclick: () => { t.setQuery({ step: step.index }); }, ondblclick: () => openGallery(n) },
      h('img', { src: imageUrl(ev.id, image), alt: `Screenshot at step ${step.index}`, loading: 'lazy' }), h('span', { class: 'n' }, `#${step.index}`)));
    });
    return strip;
  }

  function openGallery(n) {
    const list = screenshots().map(({ step, image }) => ({ src: imageUrl(ev.id, image), caption: `Step ${step.index} · ${step.title}${step.detail ? ' · ' + step.detail : ''}` }));
    lightbox.open(list, n);
  }

  function lastImageBefore(index) {
    for (let i = index - 2; i >= 0; i--) {
      const s = traj.steps[i];
      if (s.images && s.images.length) return { step: s, image: s.images[s.images.length - 1] };
    }
    return null;
  }

  function body() {
    const steps = visibleSteps();
    const index = h('nav', { class: 'card traj-index', 'aria-label': 'Steps' });
    const feed = h('div', { class: 'traj-feed' });
    if (!steps.length) feed.append(empty('No steps match this filter.'));
    for (const step of steps) {
      index.append(h('button', { type: 'button', class: [`st-${step.status}`, `k-${step.kind}`], dataset: { step: step.index },
        onclick: () => t.setQuery({ step: step.index }) },
      h('span', { class: 'i-num' }, step.index), icon(stepIcon(step)),
      h('span', { class: 'i-title' }, indexTitle(step)),
      h('span', { class: 'i-time' }, step.started_offset_ms !== undefined ? clock(step.started_offset_ms) : '')));
      feed.append(stepCard(step));
    }
    return h('div', { class: 'traj-body' }, index, feed);
  }

  function indexTitle(step) {
    if (step.kind === 'message') return step.phase === 'final_answer' ? `Final: ${step.text}` : step.text || 'Agent message';
    if (step.kind === 'reasoning') return step.hidden ? 'Reasoning' : `Reasoning: ${step.text}`;
    if (step.kind === 'prompt') return 'Instruction to agent';
    return step.title + (step.detail && step.kind !== 'tool' ? `: ${step.detail}` : '');
  }

  function meta(step) {
    const lines = step.source?.lines || [];
    return h('span', { class: 'step-meta' },
      step.duration_ms !== null && step.duration_ms !== undefined && step.kind === 'tool' ? h('span', { title: 'Recorded duration' }, duration(step.duration_ms)) : null,
      step.started_offset_ms !== undefined ? h('span', { title: step.time_basis || (step.recovered ? 'Recovered part: time unknown' : 'Time since the turn started') }, clock(step.started_offset_ms)) : null,
      step.recovered ? badge('recovered', 'outline', null, 'Recovered from the OpenCode session API; original time unknown') : null,
      lines.length ? h('button', { type: 'button', class: 'raw-link', title: `Open the original record${lines.length > 1 ? `s (${lines.length} revisions)` : ''}`,
        onclick: () => t.openRecord(step.source.path, lines[lines.length - 1]) }, icon('code'), `L${lines[0]}${lines.length > 1 ? `+${lines.length - 1}` : ''}`) : null);
  }

  function stepCard(step) {
    const final = step.kind === 'message' && step.phase === 'final_answer';
    const header = h('div', { class: 'step-header' });
    const content = h('div', { class: 'step-content' });
    if (step.kind === 'message') {
      append(header, [h('span', { class: 'step-title' }, final ? 'Agent · final answer' : 'Agent'),
        step.phase && !final ? chip(step.phase, null) : null, meta(step)]);
      content.append(h('div', { class: 'message-text md' }, markdown(step.text || '')));
    } else if (step.kind === 'prompt') {
      append(header, [h('span', { class: 'step-title' }, 'Harness → agent'), h('span', { class: 'step-detail' }, 'Instruction sent at the start of the turn'), meta(step)]);
      content.append(h('div', { class: 'message-text' }, step.text || ''));
    } else if (step.kind === 'reasoning') {
      append(header, [h('span', { class: 'step-title muted' }, 'Reasoning'),
        h('span', { class: 'step-detail muted small' }, step.hidden ? 'content not exposed by the provider' : ''), meta(step)]);
      if (!step.hidden && step.text) content.append(longText(step.text, { lines: 8 }));
    } else if (step.kind === 'tool') {
      append(header, [h('span', { class: 'step-title' }, step.title), step.detail ? h('span', { class: 'step-detail' }, step.detail) : null,
        chip(step.tool, null, { mono: true }),
        step.status !== 'ok' ? badge(human(step.status), step.status === 'incomplete' ? 'info' : 'bad') : null, meta(step)]);
      toolContent(step, content);
    } else {
      const tone = step.kind === 'end' ? (step.status === 'ok' ? 'good' : 'bad') : step.kind === 'notice' ? '' : 'bad';
      append(header, [h('span', { class: 'step-title' }, step.title),
        step.kind === 'end' && step.duration_ms ? badge(duration(step.duration_ms), tone) : null,
        step.call_id ? chip(step.call_id, 'call', { mono: true }) : null, step.code ? chip(step.code, 'code', { mono: true }) : null, meta(step)]);
      if (step.detail) content.append(h('div', { class: step.kind === 'notice' ? 'muted' : 'failure-box' }, step.kind === 'notice' ? null : icon('alert'), h('div', null, step.detail)));
      if (step.kind === 'interrupt') content.append(h('div', { class: 'muted small' }, 'The harness sent turn/interrupt to Codex. Check the preceding steps (blocked hooks, budgets or errors) for why.'));
      if (step.kind === 'blocked') content.append(h('div', { class: 'muted small' }, 'Codex asked to run a tool, and the managed preToolUse hook refused it before any bench tool was invoked. The tool name is not part of the recorded hook event.'));
    }
    const card = h('div', { class: 'step-card' }, header, content.childNodes.length ? content : null);
    return h('article', { class: ['step', `k-${step.kind}`, `st-${step.status}`, step.category && `cat-${step.category}`, final && 'final'],
      id: `step-${step.index}`, dataset: { step: step.index } },
    h('div', { class: 'step-rail' }, h('span', { class: 'step-icon' }, icon(stepIcon(step))), h('span', { class: 'step-num' }, step.index)), card);
  }

  function toolContent(step, content) {
    const args = step.arguments || {};
    if (step.failure) {
      content.append(h('div', { class: 'failure-box' }, icon('alert'), h('div', null,
        h('div', null, step.failure.message || 'Tool call failed'),
        step.failure.cause ? h('div', { class: 'cause' }, step.failure.cause) : null,
        causeHint(step.failure.cause) ? h('div', { class: 'muted small' }, causeHint(step.failure.cause)) : null,
        step.failure.raw && step.failure.raw !== step.failure.message ? h('details', null, h('summary', { class: 'muted small' }, 'Original error text'), longText(step.failure.raw, { lines: 6 })) : null)));
    }
    const writes = ['bench_write_file', 'write'].includes(step.tool) && typeof args.content === 'string';
    const shownArgs = Object.entries(args).filter(([k]) => !(writes && k === 'content'));
    const trivial = step.tool === 'gui_step' || step.tool === 'gui_open_url' || step.tool === 'gui_observe' || step.tool === 'bench_read_file' || step.tool === 'read' || step.tool === 'bench_read_image';
    if (shownArgs.length && !(trivial && !step.failure)) {
      content.append(h('dl', { class: 'args' }, shownArgs.flatMap(([k, v]) => [h('dt', null, k), h('dd', null, typeof v === 'string' ? v : JSON.stringify(v))])));
    } else if (shownArgs.length) {
      content.append(h('details', null, h('summary', { class: 'muted small' }, 'Arguments'),
        h('dl', { class: 'args' }, shownArgs.flatMap(([k, v]) => [h('dt', null, k), h('dd', null, typeof v === 'string' ? v : JSON.stringify(v))]))));
    }
    if (writes) content.append(codeView(args.content, { lang: language(args.path || args.filePath), title: args.path || args.filePath }));
    if (step.edit) {
      content.append(h('div', { class: 'grid-2' }, codeView(step.edit.old || '', { title: 'Replaced' }), codeView(step.edit.new || '', { title: 'With' })));
    }
    if (state.targets && step.point) {
      const prev = lastImageBefore(step.index);
      if (prev) {
        content.append(h('div', null, h('div', { class: 'label-sm' }, `Target (${step.point[0]}, ${step.point[1]}) on the last screenshot before this action (step ${prev.step.index})`),
          shot(imageUrl(ev.id, prev.image), { small: true, point: step.point, width: prev.image.width, height: prev.image.height,
            caption: `step ${prev.step.index}`, alt: 'Last observed screen with action target' })));
      }
    }
    const result = step.result || { kind: 'none' };
    if (result.kind === 'file' && result.file) {
      const f = result.file;
      const range = f.first_line ? `lines ${f.first_line}–${f.last_line}` : f.offset !== undefined && f.offset !== null ? `bytes ${f.offset}–${f.end_offset}${f.eof ? ' (end of file)' : ''}` : '';
      content.append(f.content !== undefined && f.content !== null
        ? longText(f.content, { code: true, lang: language(f.path), firstLine: f.first_line || 1, title: `${f.path || ''}  ${range}`, lines: 24 })
        : empty('Empty file page.'));
      if (f.note) content.append(h('div', { class: 'muted small' }, f.note));
      if (f.next_offset) content.append(h('div', { class: 'muted small' }, `More content follows from byte ${f.next_offset}.`));
    } else if (result.kind === 'files') {
      content.append(h('div', { class: 'files-list' }, result.files.map((f) => h('div', null, f.path, h('span', { class: 'k' }, `  ${f.kind || ''} · ${bytes(f.bytes)}`)))));
    } else if (result.kind === 'write' && result.write) {
      content.append(h('div', { class: 'muted small' }, `Wrote ${bytes(result.write.bytes)} · sha256 ${String(result.write.sha256 || '').slice(0, 12)}${result.write.previous_sha256 ? ' · replaced an earlier version' : ''}`));
    } else if (result.kind === 'ui_tree') {
      content.append(h('div', null, h('div', { class: 'label-sm' }, 'UI structure returned'), longText(result.text, { lines: 14, wrap: false })));
    } else if (result.kind === 'ack') {
      if (step.status === 'ok') content.append(h('div', { class: 'muted small' }, result.text));
    } else if (result.kind === 'text' && result.text && !step.failure) {
      content.append(longText(result.text, { lines: 14 }));
    }
    if (step.images && step.images.length) {
      const all = screenshots();
      const row = h('div', { class: 'shot-row' });
      step.images.forEach((image, i) => {
        const n = all.findIndex((x) => x.step === step && x.i === i);
        const reference = args.reference ? `reference “${args.reference}”` : null;
        row.append(shot(imageUrl(ev.id, image), { caption: [reference, image.width ? `${image.width}×${image.height}` : null].filter(Boolean).join(' · '),
          alt: `Screenshot returned at step ${step.index}`, onopen: () => openGallery(n) }));
      });
      content.append(row);
    }
    if (step.bridge) {
      content.append(h('div', { class: 'row' }, h('button', { type: 'button', class: 'raw-link', onclick: () => t.openRecord(step.bridge.path, step.bridge.line) },
        icon('link'), `Bridge record L${step.bridge.line}`)));
    }
  }

  function focus(index, scroll) {
    activeIndex = index;
    root.querySelectorAll('.step.active, .traj-index button.active, .filmstrip button.active').forEach((n) => n.classList.remove('active'));
    const node = root.querySelector(`#step-${index}`);
    root.querySelectorAll(`[data-step="${index}"]`).forEach((n) => n.classList.add('active'));
    if (node) {
      node.classList.add('active');
      const item = root.querySelector(`.traj-index button[data-step="${index}"]`);
      if (item) within(item.parentElement, item, 'y');
      const film = root.querySelector(`.filmstrip button[data-step="${index}"]`);
      if (film) within(film.parentElement, film, 'x');
      if (scroll) node.scrollIntoView({ block: 'start', behavior: scroll === 'instant' ? 'auto' : 'smooth' });
    }
  }

  // Scroll a nested container without moving the page (scrollIntoView would cancel the page scroll).
  function within(container, el, axis) {
    if (axis === 'y') {
      const top = el.offsetTop - container.offsetTop;
      if (top < container.scrollTop || top + el.offsetHeight > container.scrollTop + container.clientHeight) container.scrollTop = top - container.clientHeight / 3;
    } else {
      const left = el.offsetLeft - container.offsetLeft;
      if (left < container.scrollLeft || left + el.offsetWidth > container.scrollLeft + container.clientWidth) container.scrollLeft = left - container.clientWidth / 3;
    }
  }

  function move(delta, problemsOnly) {
    const steps = visibleSteps().filter((s) => !problemsOnly || stepMatches(s, 'problems', ''));
    if (!steps.length) return;
    const pos = steps.findIndex((s) => s.index === activeIndex);
    let next;
    if (pos === -1) next = delta > 0 ? steps.find((s) => s.index > (activeIndex || 0)) || steps[0] : [...steps].reverse().find((s) => s.index < (activeIndex || Infinity)) || steps[steps.length - 1];
    else next = steps[Math.max(0, Math.min(steps.length - 1, pos + delta))];
    t.setQuery({ step: next.index });
  }

  await draw();
  return {
    async update(route) {
      const next = read(route);
      const redraw = next.trial.id !== state.trial.id || next.filter !== state.filter || next.q !== state.q
        || next.notices !== state.notices || next.targets !== state.targets;
      const typing = document.activeElement && document.activeElement.type === 'search';
      state = next;
      if (redraw) {
        const y = window.scrollY;
        await draw();
        if (typing) { const input = root.querySelector('input[type="search"]'); input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
        if (!state.step) window.scrollTo(0, y);
      } else if (state.step) focus(state.step, true);
    },
    key(e) {
      if (e.key === 'j') { move(1); return true; }
      if (e.key === 'k') { move(-1); return true; }
      if (e.key === 'n') { move(1, true); return true; }
      if (e.key === 'p') { move(-1, true); return true; }
      return false;
    },
  };
}
