// Runs library: every recorded run with progress, credit and problems at a glance.
import { api } from './api.js';
import { activate, badge, chip, clear, empty, h, icon, outcomeBadge, segmented } from './dom.js';
import { RUNNER_LABELS, ago, armLabel, attemptOutcome, formatNumber, human, runnerOf, taskName, when } from './format.js';

const STATUS_TONES = { complete: 'good', completed_with_errors: 'warn', running: 'info', interrupted: 'warn', stopped: 'warn',
  blocked: 'bad', preflight_failed: 'bad', recorded: '', incomplete: 'info' };

export function summarize(run) {
  const counts = { credited: 0, zero: 0, error: 0, interrupted: 0, running: 0, missing: 0, unpaired: 0, unresolved: 0 };
  const runners = new Set();
  const models = new Set(run.models || []);
  for (const task of run.tasks) {
    for (const cell of task.cells) {
      const first = cell.attempts[0];
      counts[attemptOutcome(first)] += 1;
      for (const attempt of cell.attempts) if (attempt.record) runners.add(runnerOf(attempt.record));
    }
  }
  const planned = run.totals.planned;
  return { counts, planned, runners: [...runners], models: [...models] };
}

function progress(summary) {
  const { counts, planned } = summary;
  const pct = (n) => `${planned ? (n / planned) * 100 : 0}%`;
  const finished = planned - counts.running - counts.missing - counts.interrupted;
  return h('div', { class: 'run-progress' },
    h('div', { class: 'bar', title: `${counts.credited} credited · ${counts.zero} zero credit · ${counts.error} errors · ${counts.interrupted} interrupted · ${counts.running} running` },
      ['credited', 'zero', 'error', 'interrupted', 'running', 'unpaired', 'unresolved'].map((k) => (counts[k] ? h('span', { class: k, style: { width: pct(counts[k]) } }) : null))),
    h('div', { class: 'meta' }, h('span', null, `${formatNumber(finished)} / ${formatNumber(planned)} finished`),
      h('span', null, `${formatNumber(counts.credited)} credited`)));
}

export async function renderRuns(root, route, ctx) {
  let data = await api.hierarchy();
  let signature = JSON.stringify(data);
  const state = { q: route.query.get('q') || '', runner: route.query.get('runner') || 'all', singles: route.query.get('singles') === '1' };

  function draw() {
    const grouped = data.runs.filter((r) => r.kind !== 'single');
    const singles = data.runs.filter((r) => r.kind === 'single');
    const rows = grouped.map((run) => ({ run, s: summarize(run) }));
    const singleRows = singles.map((run) => ({ run, s: summarize(run) }));
    const runnerCounts = {};
    for (const { s } of [...rows, ...singleRows]) for (const r of s.runners) runnerCounts[r] = (runnerCounts[r] || 0) + 1;
    const match = ({ run, s }) => {
      if (state.runner !== 'all' && !s.runners.includes(state.runner)) return false;
      if (!state.q) return true;
      const hay = [run.name, run.path, run.scope, ...s.models, ...run.tasks.map((t) => t.id), ...run.platforms].join(' ').toLowerCase();
      return hay.includes(state.q.toLowerCase());
    };
    const totals = { evaluations: data.evaluations.length, credited: 0, errors: 0, running: 0 };
    for (const { s } of rows) { totals.credited += s.counts.credited; totals.errors += s.counts.error; totals.running += s.counts.running; }

    const page = h('div', { class: 'page' });
    page.append(
      h('div', { class: 'page-head' }, h('div', null,
        h('h1', null, 'Runs'),
        h('p', { class: 'lede' }, 'Every recorded run in this evidence folder. Open a run to see its task × arm outcome matrix, then drill into any evaluation for its verdict, trajectory, submission and paired execution evidence.'))),
      h('div', { class: 'stats' },
        stat('Grouped runs', grouped.length, `${singles.length} individual evaluations`),
        stat('Evaluations indexed', totals.evaluations, 'All arm evaluations on disk'),
        stat('Credited pairs', totals.credited, 'First attempts in grouped runs', 'good'),
        stat('Errors', totals.errors, 'Invalid or missing results', totals.errors ? 'warn' : ''),
        stat('Running', totals.running, 'Recorded as running', totals.running ? 'info' : '')),
      h('div', { class: 'toolbar' },
        h('input', { type: 'search', placeholder: 'Search runs, tasks, models…', value: state.q, 'aria-label': 'Search runs',
          oninput: (e) => { state.q = e.target.value; ctx.setQuery({ q: state.q || null }); } }),
        segmented([{ value: 'all', label: 'All agents' }, ...['claude', 'codex', 'cursor', 'opencode', 'reference', 'scripted'].filter((r) => runnerCounts[r])
          .map((r) => ({ value: r, label: RUNNER_LABELS[r], count: runnerCounts[r] }))], state.runner,
        (v) => { state.runner = v; ctx.setQuery({ runner: v === 'all' ? null : v }); }),
        h('span', { class: 'spacer' }),
        h('span', { class: 'muted small' }, `Updated ${new Date().toLocaleTimeString()}`)));

    const visible = rows.filter(match);
    page.append(visible.length ? h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, runTable(visible, ctx)))
      : empty(rows.length ? 'No grouped runs match these filters.' : 'No grouped runs recorded yet.'));

    const visibleSingles = singleRows.filter(match);
    if (singleRows.length) {
      const fold = h('details', { class: 'fold', open: state.singles || null, ontoggle: (e) => { if (e.target.open !== state.singles) ctx.setQuery({ singles: e.target.open ? '1' : null }); } },
        h('summary', null, icon('chevronRight', 'icon chev'), `Individual evaluations not part of a grouped run (${visibleSingles.length})`),
        visibleSingles.length ? h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, singleTable(visibleSingles, ctx))) : empty('None match these filters.'));
      page.append(h('div', { style: { marginTop: '18px' } }, fold));
    }
    if (data.warnings && data.warnings.length) {
      page.append(h('div', { style: { marginTop: '18px' } }, h('div', { class: 'callout warn' }, icon('alert'),
        h('div', null, h('strong', null, 'Some run manifests could not be grouped. '), 'Their individual evaluations remain listed.',
          h('ul', null, data.warnings.map((w) => h('li', { class: 'mono small' }, w)))))));
    }
    clear(root).append(page);
  }

  ctx.setCrumbs([{ label: 'Runs', href: '#/' }]);
  draw();
  return {
    update(next) {
      state.q = next.query.get('q') || '';
      state.runner = next.query.get('runner') || 'all';
      state.singles = next.query.get('singles') === '1';
      const focused = document.activeElement && document.activeElement.type === 'search';
      draw();
      if (focused) { const input = root.querySelector('input[type="search"]'); input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
    },
    async poll() {
      const next = await api.hierarchy();
      const sig = JSON.stringify(next);
      if (sig !== signature) {
        data = next; signature = sig;
        if (!(document.activeElement && document.activeElement.type === 'search')) draw();
      }
    },
  };
}

function stat(label, value, sub, tone) {
  return h('div', { class: ['stat', tone] }, h('div', { class: 'label' }, label), h('div', { class: 'value' }, formatNumber(value)), h('div', { class: 'sub' }, sub));
}

function runTable(rows, ctx) {
  const table = h('table', { class: 'table' },
    h('thead', null, h('tr', null, ['Run', 'Agent', 'Scope', 'Progress', 'Problems', 'Status', 'Updated'].map((c) => h('th', null, c)))));
  const body = h('tbody');
  for (const { run, s } of rows) {
    const open = () => ctx.navigate({ page: 'run', run: run.id, query: new URLSearchParams() });
    const problems = [];
    if (s.counts.error) problems.push(badge(`${s.counts.error} errors`, 'error', 'alert'));
    if (s.counts.interrupted) problems.push(badge(`${s.counts.interrupted} interrupted`, 'error', 'stop'));
    if (s.counts.zero) problems.push(badge(`${s.counts.zero} zero credit`, 'zero', 'x'));
    if (s.counts.running) problems.push(badge(`${s.counts.running} running`, 'running', 'clock'));
    if (s.counts.missing) problems.push(badge(`${s.counts.missing} not recorded`, 'outline'));
    body.append(h('tr', { class: 'link run-row', onclick: open, tabindex: '0', onkeydown: (e) => { if (e.key === 'Enter') open(); } },
      h('td', null, h('a', { class: 'name', href: ctx.href({ page: 'run', run: run.id }), onclick: (e) => e.stopPropagation() }, run.name),
        h('div', { class: 'path' }, run.path)),
      h('td', null, h('div', { class: 'row' }, s.runners.map((r) => chip(RUNNER_LABELS[r] || r, null, { icon: r === 'codex' || r === 'opencode' ? 'terminal' : 'shieldCheck' }))),
        h('div', { class: 'muted small', style: { marginTop: '4px' } }, s.models.join(', '))),
      h('td', null, h('div', { class: 'nowrap' }, `${run.tasks.length} ${run.tasks.length === 1 ? 'task' : 'tasks'} · ${run.arms.length} arms`),
        h('div', { class: 'muted small' }, run.platforms.join(' · ') || '—')),
      h('td', null, progress(s)),
      h('td', null, h('div', { class: 'row' }, problems.length ? problems : h('span', { class: 'muted small' }, 'None'))),
      h('td', null, badge(human(run.status), STATUS_TONES[run.status] || '')),
      h('td', { class: 'nowrap muted', title: when(run.modified) }, ago(run.modified))));
  }
  table.append(body);
  return table;
}

function singleTable(rows, ctx) {
  const table = h('table', { class: 'table' },
    h('thead', null, h('tr', null, ['Task', 'Arm', 'Agent', 'Outcome', 'Path', 'Updated'].map((c) => h('th', null, c)))));
  const body = h('tbody');
  for (const { run } of rows) {
    const cell = run.tasks[0].cells[0];
    const record = cell.attempts[0] && cell.attempts[0].record;
    const outcome = attemptOutcome(cell.attempts[0]);
    const target = record ? { page: 'eval', run: null, id: record.id } : null;
    body.append(h('tr', target ? { class: 'link', ...activate(() => ctx.navigate(target)) } : null,
      h('td', { class: 'title-cell' }, taskName(cell.task), h('div', { class: 'sub' }, cell.task)),
      h('td', null, armLabel(cell.arm)),
      h('td', null, record ? `${RUNNER_LABELS[runnerOf(record)]} · ${record.model}` : '—'),
      h('td', null, outcomeBadge(outcome)),
      h('td', { class: 'sub' }, run.path),
      h('td', { class: 'nowrap muted' }, ago(run.modified))));
  }
  table.append(body);
  return table;
}
