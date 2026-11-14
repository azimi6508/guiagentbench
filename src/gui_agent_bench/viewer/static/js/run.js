// Run overview: outcome matrix, credit breakdowns, loss reasons and evaluation table.
import { api } from './api.js';
import { OUTCOME_ICONS, activate, badge, card, chip, clear, empty, h, icon, outcomeBadge, segmented } from './dom.js';
import { ARM_ORDER, OUTCOMES, RUNNER_LABELS, ago, armLabel, compact, formatNumber, human, seconds, taskName, when } from './format.js';
import { summarize } from './runs.js';

const ORDER = ['credited', 'zero', 'error', 'interrupted', 'running', 'unpaired', 'unresolved', 'missing'];

export async function renderRun(root, route, ctx) {
  let data = await api.overview(route.run);
  let signature = JSON.stringify(data);
  let state = readState(route);

  function readState(r) {
    return { outcome: r.query.get('outcome') || 'all', arm: r.query.get('arm') || '', domain: r.query.get('domain') || '',
      reason: r.query.get('reason') || '', q: r.query.get('q') || '', sort: r.query.get('sort') || '' };
  }

  function filtered() {
    return data.cells.filter((c) => (state.outcome === 'all' || c.outcome === state.outcome)
      && (!state.arm || c.arm === state.arm) && (!state.domain || c.task.split('/')[0] === state.domain)
      && (!state.reason || c.reason === state.reason)
      && (!state.q || `${c.task} ${c.arm} ${c.model} ${c.reason}`.toLowerCase().includes(state.q.toLowerCase())));
  }

  function draw() {
    const run = data.run;
    const s = summarize(run);
    ctx.setCrumbs([{ label: 'Runs', href: '#/' }, { label: run.name }]);
    const cells = data.cells;
    const sum = (key) => cells.reduce((n, c) => n + (typeof c[key] === 'number' ? c[key] : 0), 0);
    const known = (key) => cells.some((c) => typeof c[key] === 'number');
    const finished = s.planned - s.counts.running - s.counts.missing - s.counts.interrupted;
    const firstProblem = cells.find((c) => c.evaluation && c.outcome === 'error')
      || cells.find((c) => c.evaluation && ['interrupted', 'zero'].includes(c.outcome));
    const page = h('div', { class: 'page' });
    page.append(h('div', { class: 'page-head' },
      h('div', { class: 'grow' },
        h('div', { class: 'eyebrow' }, run.kind === 'single' ? 'Individual evaluation' : run.kind === 'historical' ? 'Historical run' : 'Run'),
        h('h1', null, run.name),
        run.scope ? h('p', { class: 'lede' }, run.scope) : null,
        h('div', { class: 'row', style: { marginTop: '10px' } },
          badge(human(run.status), { complete: 'good', completed_with_errors: 'warn', running: 'info', interrupted: 'warn', preflight_failed: 'bad' }[run.status] || ''),
          s.runners.map((r) => chip(RUNNER_LABELS[r] || r, 'agent', { icon: 'terminal' })),
          s.models.map((m) => chip(m, 'model', { mono: true })),
          run.platforms.map((p) => chip(p, 'domain')),
          chip(run.path, null, { mono: true, icon: 'folder', title: 'Run folder relative to the viewer root' }),
          h('span', { class: 'muted small', title: when(run.modified) }, `Updated ${ago(run.modified)}`))),
      h('div', { class: 'row' }, firstProblem ? h('a', { class: 'btn', href: ctx.href({ page: 'eval', run: route.run, id: firstProblem.evaluation }) },
        icon('alert'), 'First problem') : null,
      cells[0] && cells[0].evaluation ? h('a', { class: 'btn btn-primary', href: ctx.href({ page: 'eval', run: route.run, id: cells[0].evaluation }) },
        icon('play'), 'Review evaluations') : null)));

    if (run.status === 'preflight_failed' || run.preflight?.status === 'failed') {
      const checks = run.preflight?.checks || run.preflight?.failures || [];
      const failed = checks.filter((c) => c.status !== 'passed');
      const passed = checks.filter((c) => c.status === 'passed');
      page.append(h('div', { class: 'callout bad', style: { marginBottom: '16px' } }, icon('alert'), h('div', { class: 'grow' },
        h('strong', null, 'Preflight failed. '), `No evaluations were started; the full plan is retained. ${failed.length} of ${checks.length} prerequisite checks failed.`,
        h('ul', { class: 'checks', style: { marginTop: '8px' } }, failed.map((c) => h('li', { class: 'fail' }, icon('x'),
          h('div', null, h('span', { class: 'mono small' }, [c.name, c.image || c.task || c.arm].filter(Boolean).join(' · ')),
            h('div', { class: 'detail' }, c.message || human(c.status)))))),
        passed.length ? h('div', { class: 'muted small' }, `Passed: ${[...new Set(passed.map((c) => c.name))].join(', ')}`) : null)));
    } else if (run.status === 'completed_with_errors') {
      page.append(h('div', { class: 'callout warn', style: { marginBottom: '16px' } }, icon('alert'), h('div', null,
        h('strong', null, 'Finished with errors that need review. '),
        `${s.counts.error} of ${s.planned} planned evaluations hit a framework, environment, provider or unclassified failure and earn zero credit. `
        + 'Zero-credit results the model caused itself are counted separately. All evidence is retained; there were no automatic retries.')));
    } else if (run.status === 'interrupted') {
      page.append(h('div', { class: 'callout warn', style: { marginBottom: '16px' } }, icon('stop'), h('div', null,
        h('strong', null, 'Interrupted. '),
        `The run stopped early: ${s.counts.interrupted} evaluation(s) were cut off and ${s.counts.missing} were never started. All planned evaluations stay in the denominator with zero credit; there were no automatic retries.`)));
    } else if (run.stop_reason) {
      page.append(h('div', { class: 'callout warn', style: { marginBottom: '16px' } }, icon('alert'), h('div', null, h('strong', null, 'Stopped. '), String(run.stop_reason))));
    }

    page.append(h('div', { class: 'stats' },
      stat('Planned', s.planned, `${run.tasks.length} tasks × ${run.arms.length} arms${s.planned > run.tasks.length * run.arms.length ? ' (models / repeats)' : ''}`),
      stat('Finished', finished, `${formatNumber(s.planned - finished)} running or not recorded`),
      stat('Credited', s.counts.credited, s.planned ? `${((s.counts.credited / s.planned) * 100).toFixed(1)}% of planned pairs` : '', 'good'),
      stat('Zero credit', s.counts.zero, 'Model outcome: wrong result or invalid submission', s.counts.zero ? 'bad' : ''),
      stat('Errors', s.counts.error + s.counts.interrupted, 'Framework, environment or interruption; needs review', s.counts.error + s.counts.interrupted ? 'warn' : ''),
      stat('Agent time', known('authoring_seconds') ? seconds(sum('authoring_seconds')) : '—', 'Sum of recorded authoring sessions'),
      stat('Tokens', known('tokens') ? compact(sum('tokens')) : '—', 'Recorded usage only')));

    page.append(h('div', { class: 'grid-3' },
      card('Credit by arm', armBars(cells), { icon: 'layers' }),
      card('Why credit was lost', reasonBars(cells, state, ctx), { icon: 'alert',
        foot: 'First attempts only. Click a reason to filter the table and matrix.' }),
      card('By domain', domainBars(cells), { icon: 'globe' })));

    page.append(h('div', { class: 'section-title' }, h('h2', null, 'Outcome matrix'), legend()));
    page.append(h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, matrix(run, cells, route, ctx, filtered()))));

    const rows = filtered();
    page.append(h('div', { class: 'section-title' }, h('h2', null, `Evaluations (${rows.length} of ${cells.length})`)));
    const counts = Object.fromEntries(ORDER.map((o) => [o, cells.filter((c) => c.outcome === o).length]));
    const arms = ARM_ORDER.filter((a) => cells.some((c) => c.arm === a));
    const domains = [...new Set(cells.map((c) => c.task.split('/')[0]))];
    page.append(h('div', { class: 'toolbar' },
      segmented([{ value: 'all', label: 'All', count: cells.length },
        ...ORDER.filter((o) => counts[o]).map((o) => ({ value: o, label: OUTCOMES[o].label, count: counts[o] }))],
      state.outcome, (v) => ctx.setQuery({ outcome: v === 'all' ? null : v })),
      select('All arms', state.arm, arms.map((a) => [a, armLabel(a)]), (v) => ctx.setQuery({ arm: v })),
      domains.length > 1 ? select('All domains', state.domain, domains.map((d) => [d, d]), (v) => ctx.setQuery({ domain: v })) : null,
      state.reason ? h('button', { class: 'btn btn-sm', type: 'button', onclick: () => ctx.setQuery({ reason: null }) }, icon('x'), `Reason: ${state.reason}`) : null,
      h('span', { class: 'spacer' }),
      h('input', { type: 'search', placeholder: 'Filter evaluations…', 'aria-label': 'Filter evaluations', value: state.q, oninput: (e) => ctx.setQuery({ q: e.target.value || null }) })));
    page.append(rows.length ? h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, table(rows, route, ctx, { ...state, all: cells }))) : empty('No evaluations match these filters.'));
    if (data.warnings && data.warnings.length) {
      page.append(h('div', { class: 'callout warn', style: { marginTop: '16px' } }, icon('alert'), h('div', null, data.warnings.join(' · '))));
    }
    clear(root).append(page);
  }

  draw();
  return {
    update(next) {
      state = readState(next);
      const focused = document.activeElement && document.activeElement.type === 'search';
      const y = window.scrollY;
      draw();
      window.scrollTo(0, y);
      if (focused) { const input = root.querySelector('input[type="search"]'); input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
    },
    async poll() {
      const next = await api.overview(route.run);
      const sig = JSON.stringify(next);
      if (sig !== signature) {
        data = next; signature = sig;
        const y = window.scrollY;
        if (!(document.activeElement && document.activeElement.type === 'search')) { draw(); window.scrollTo(0, y); }
      }
    },
    key(e) {
      if (e.key === 'Enter' && data.cells[0]?.evaluation) ctx.navigate({ page: 'eval', run: route.run, id: data.cells[0].evaluation });
    },
  };
}

function stat(label, value, sub, tone) {
  return h('div', { class: ['stat', tone] }, h('div', { class: 'label' }, label),
    h('div', { class: 'value' }, typeof value === 'number' ? formatNumber(value) : value), h('div', { class: 'sub' }, sub));
}

function select(placeholder, value, options, onchange) {
  return h('select', { onchange: (e) => onchange(e.target.value || null), 'aria-label': placeholder },
    h('option', { value: '' }, placeholder), options.map(([v, label]) => h('option', { value: v, selected: v === value || null }, label)));
}

function stacked(groups, labelOf) {
  const bars = h('div', { class: 'hbars' });
  for (const [key, list] of groups) {
    const total = list.length;
    const counts = Object.fromEntries(ORDER.map((o) => [o, list.filter((c) => c.outcome === o).length]));
    bars.append(h('div', { class: 'hbar', title: ORDER.filter((o) => counts[o]).map((o) => `${OUTCOMES[o].label}: ${counts[o]}`).join(' · ') },
      h('span', { class: 'hbar-label' }, labelOf(key)),
      h('span', { class: 'hbar-track' }, ORDER.map((o) => (counts[o] ? h('span', { class: `bar-${o}`, style: { width: `${(counts[o] / total) * 100}%`, background: `var(--${toneVar(o)})` } }) : null))),
      h('span', { class: 'hbar-value' }, `${counts.credited}/${total}`)));
  }
  return bars;
}

function toneVar(outcome) {
  return { credited: 'good', zero: 'bad', error: 'warn', interrupted: 'warn', running: 'info' }[outcome] || 'border-strong';
}

function armBars(cells) {
  const groups = ARM_ORDER.filter((a) => cells.some((c) => c.arm === a)).map((a) => [a, cells.filter((c) => c.arm === a)]);
  return stacked(groups, armLabel);
}

function domainBars(cells) {
  const domains = [...new Set(cells.map((c) => c.task.split('/')[0]))];
  return stacked(domains.map((d) => [d, cells.filter((c) => c.task.startsWith(d + '/'))]), (d) => d);
}

function reasonBars(cells, state, ctx) {
  const lost = cells.filter((c) => ['zero', 'error', 'interrupted'].includes(c.outcome));
  if (!lost.length) return h('p', { class: 'muted' }, 'No first attempt lost credit.');
  const counts = {};
  for (const c of lost) counts[c.reason] = (counts[c.reason] || 0) + 1;
  const max = Math.max(...Object.values(counts));
  const bars = h('div', { class: 'hbars' });
  for (const [reason, n] of Object.entries(counts).sort((a, b) => b[1] - a[1])) {
    const tone = lost.find((c) => c.reason === reason).outcome === 'zero' ? 'bad' : 'warn';
    bars.append(h('div', { class: ['hbar', 'clickable', state.reason === reason && 'active'], role: 'button', 'aria-pressed': String(state.reason === reason),
      ...activate(() => ctx.setQuery({ reason: state.reason === reason ? null : reason })) },
    h('span', { class: 'hbar-label', title: reason }, reason),
    h('span', { class: 'hbar-track' }, h('span', { style: { width: `${(n / max) * 100}%`, background: `var(--${tone})` } })),
    h('span', { class: 'hbar-value' }, n)));
  }
  return bars;
}

function legend() {
  return h('div', { class: 'legend' }, ['credited', 'zero', 'error', 'interrupted', 'running', 'missing'].map((o) =>
    h('span', null, h('span', { class: ['dot', o] }), OUTCOMES[o].label)));
}

function matrix(run, cells, route, ctx, visible) {
  const arms = ARM_ORDER.filter((a) => cells.some((c) => c.arm === a));
  const shown = new Set(visible);
  const table = h('table', { class: 'matrix' }, h('thead', null, h('tr', null, h('th', null, 'Task'), arms.map((a) => h('th', null, armLabel(a))))));
  const body = h('tbody');
  for (const task of run.tasks) {
    const row = h('tr', null, h('td', { class: 'task-cell' }, h('div', { class: 't' }, taskName(task.id)), h('div', { class: 'p' }, task.id)));
    for (const arm of arms) {
      const here = cells.filter((c) => c.task === task.id && c.arm === arm);
      const td = h('td');
      if (!here.length) td.append(h('div', { class: 'mcell na', title: 'Not planned for this task' }, 'Not planned'));
      for (const c of here) {
        const facts = [c.authoring_seconds != null ? seconds(c.authoring_seconds) : null, c.tool_calls != null ? `${c.tool_calls} calls` : null].filter(Boolean).join(' · ');
        const label = here.length > 1 ? `${c.model}${c.repeat > 1 ? ` · r${c.repeat}` : ''}` : null;
        const content = [h('span', { class: 'top' }, icon(OUTCOME_ICONS[c.outcome] || 'minus'), OUTCOMES[c.outcome].label),
          h('span', { class: 'reason' }, c.outcome === 'credited' ? (label || 'Paired reward 1') : (c.reason || '')),
          label && c.outcome !== 'credited' ? h('span', { class: 'facts' }, label) : null,
          facts ? h('span', { class: 'facts' }, facts) : null,
          c.attempts > 1 ? h('span', { class: 'facts' }, `${c.attempts} attempts (first shown)`) : null,
          c.lineage === 'pending' ? h('span', { class: 'facts', title: 'The controller attests run lineage when the evaluation finishes' }, 'lineage pending') : null,
          c.lineage === 'unattested' ? h('span', { class: 'facts', title: 'The run ended before the controller could attest this evaluation' }, 'lineage unattested') : null];
        td.append(c.evaluation
          ? h('a', { class: ['mcell', c.outcome, !shown.has(c) && 'dimmed'], href: ctx.href({ page: 'eval', run: route.run, id: c.evaluation }), title: `${task.id} · ${armLabel(arm)}` }, content)
          : h('div', { class: ['mcell', 'na'], title: c.error || c.reason || 'No evidence recorded' }, OUTCOMES[c.outcome].label,
            c.outcome === 'running' ? h('span', { class: 'facts' }, 'no evidence linked yet') : null));
      }
      row.append(td);
    }
    body.append(row);
  }
  table.append(body);
  return table;
}

const COLUMNS = [
  ['task', 'Task', (c) => c.task], ['arm', 'Arm', (c) => ARM_ORDER.indexOf(c.arm)], ['outcome', 'Outcome', (c) => ORDER.indexOf(c.outcome)],
  ['reason', 'Reason', (c) => c.reason || ''], ['authoring_seconds', 'Agent time', (c) => c.authoring_seconds ?? -1, true],
  ['tool_calls', 'Tool calls', (c) => c.tool_calls ?? -1, true], ['tokens', 'Tokens', (c) => c.tokens ?? -1, true],
];

function table(rows, route, ctx, state) {
  const [sortKey, dir] = (state.sort || ':').split(':');
  const column = COLUMNS.find((c) => c[0] === sortKey);
  const sorted = column ? [...rows].sort((a, b) => {
    const x = column[2](a); const y = column[2](b);
    return (x < y ? -1 : x > y ? 1 : 0) * (dir === 'desc' ? -1 : 1);
  }) : rows;
  const head = h('tr', null, h('th', null, '#'), COLUMNS.map(([key, label, , right]) => h('th', {
    class: ['sortable', right && 'right'], 'aria-sort': sortKey === key ? (dir === 'desc' ? 'descending' : 'ascending') : null,
    ...activate(() => ctx.setQuery({ sort: sortKey === key && dir !== 'desc' ? `${key}:desc` : sortKey === key ? null : `${key}:asc` })),
  }, label, sortKey === key ? h('span', { class: 'arrow' }, dir === 'desc' ? '↓' : '↑') : null)), h('th', null, 'Model'));
  const body = h('tbody');
  for (const c of sorted) {
    const n = state.all.indexOf(c) + 1;
    const open = c.evaluation ? () => ctx.navigate({ page: 'eval', run: route.run, id: c.evaluation }) : null;
    body.append(h('tr', open ? { class: 'link', ...activate(open) } : null,
      h('td', { class: 'muted num' }, n),
      h('td', { class: 'title-cell' }, taskName(c.task), h('div', { class: 'sub' }, c.task)),
      h('td', null, armLabel(c.arm)),
      h('td', null, outcomeBadge(c.outcome)),
      h('td', null, c.outcome === 'credited' ? h('span', { class: 'muted' }, '—') : c.reason || '—', c.attempts > 1 ? h('div', { class: 'muted small' }, `${c.attempts} attempts`) : null),
      h('td', { class: 'right num' }, seconds(c.authoring_seconds)),
      h('td', { class: 'right num' }, formatNumber(c.tool_calls)),
      h('td', { class: 'right num' }, compact(c.tokens)),
      h('td', { class: 'sub' }, c.model)));
  }
  return h('table', { class: 'table' }, h('thead', null, head), body);
}
