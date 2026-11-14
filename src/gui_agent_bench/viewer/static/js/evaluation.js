// Evaluation review: verdict, trials, issues, integrity, configuration and task inputs.
import { api, artifactUrl } from './api.js';
import { OUTCOME_ICONS, badge, callout, card, chip, clear, codeView, empty, h, icon, jsonView, kv, markdown, shot } from './dom.js';
import {
  ARM_ORDER, IMPACT, OUTCOMES, RUNNER_LABELS, armLabel, bytes, causeHint, causeText, compact, formatNumber, human,
  seconds, shortHash, taskName,
} from './format.js';
import { renderTrajectory, loadTrajectory, clearTrajectories } from './trajectory.js';
import { renderSubmission, renderExecution } from './execution.js';
import { renderFiles, openRecord } from './files.js';

const overviews = new Map();

async function runOverview(run, force) {
  if (!run) return null;
  if (!force && overviews.has(run)) return overviews.get(run);
  try {
    const value = await api.overview(run);
    overviews.set(run, value);
    return value;
  } catch {
    return null;
  }
}

export function trialLabel(ev, trial) {
  if (ev.arm.family === 'judge') return trial.variant === 'faulty' ? 'Faulty-state recording' : 'Correct-state recording';
  return ev.trials.length > 1 ? `Authoring session (${trial.variant})` : 'Authoring session';
}

export function trialShort(ev, trial) {
  if (ev.arm.family === 'judge') return trial.variant === 'faulty' ? 'Faulty state' : 'Correct state';
  return 'Authoring';
}

export function verdictTitle(ev, outcome = ev.outcome) {
  const o = outcome;
  if (o === 'credited') return 'Credited — paired reward 1';
  if (o === 'running') return 'Running — results are provisional';
  if (o === 'interrupted') return 'Interrupted — the run stopped before grading · zero credit';
  if (o === 'error') return `Error — ${ev.reason} · zero credit, needs review`;
  if (o === 'zero') return `Zero credit — ${ev.reason}`;
  if (o === 'unpaired') return 'Single-state result — no paired score';
  return OUTCOMES[o]?.label || human(o);
}

export function allIssues(ev) {
  const out = [];
  const seen = new Set();
  const push = (issue, where, source) => {
    const trialPart = where.split(' · ')[0];
    const key = JSON.stringify([trialPart, issue.cause, issue.message, issue.source, issue.execution_index]);
    if (seen.has(key)) {
      const existing = out.find((x) => x.key === key);
      if (existing && issue.operation && !existing.operations.includes(issue.operation)) existing.operations.push(issue.operation);
      return;
    }
    seen.add(key);
    out.push({ ...issue, key, where, operations: issue.operation ? [issue.operation] : [], sourceLink: source });
  };
  for (const t of ev.trials) {
    const label = trialShort(ev, t);
    for (const issue of t.agent?.issues || []) push(issue, `${label} · agent`, null);
    for (const e of t.executions) {
      for (const issue of e.issues) {
        const file = issue.source?.file ? `${e.files['result.json'].replace(/result\.json$/, '')}${issue.source.file}` : null;
        const line = typeof issue.source?.record_index === 'number' ? issue.source.record_index + 1 : null;
        push(issue, `${human(e.variant)} app execution`, file ? { path: file, line } : null);
      }
    }
    for (const issue of t.issues) {
      if (issue.phase === 'execution' && t.executions.length) continue;
      push(issue, `${label} · ${issue.phase || 'grading'}`, null);
    }
  }
  return out;
}

export async function renderEvaluation(root, route, ctx) {
  let ev = await api.evaluation(route.id);
  let overview = await runOverview(route.run);
  let tabState = {};
  let currentRoute = route;
  let tabHandle = null;
  const layout = h('div', { class: ['eval-layout', !overview && 'no-nav'] });
  const nav = h('aside', { class: 'eval-nav', 'aria-label': 'Evaluations in this run' });
  const main = h('section', { class: 'eval-main' });
  if (overview) layout.append(nav);
  layout.append(main);
  clear(root).append(layout);

  const order = () => (overview ? overview.cells.filter((c) => c.evaluation) : []);
  const neighbours = () => {
    const list = order();
    const i = list.findIndex((c) => c.evaluation === currentRoute.id);
    return { prev: i > 0 ? list[i - 1] : null, next: i >= 0 && i < list.length - 1 ? list[i + 1] : null, index: i, total: list.length };
  };
  const evalRoute = (id, tab, query) => ({ page: 'eval', run: currentRoute.run, id, tab: tab || 'overview', query: query || new URLSearchParams() });

  function tabs() {
    const steps = ev.trials.reduce((n, t) => n + (t.trajectory?.stats?.steps || 0), 0);
    const issues = allIssues(ev).filter((i) => i.impact === 'zero_credit').length;
    const list = [['overview', 'Overview', 'layers', issues ? [issues, 'bad'] : null],
      ['trajectory', 'Trajectory', 'list', steps ? [steps, ''] : null],
      ['submission', 'Submission', 'box', null]];
    if (ev.arm.generated) list.push(['execution', 'Paired execution', 'beaker', null]);
    list.push(['task', 'Task & inputs', 'target', null], ['files', 'Files', 'folder', [ev.artifacts.length, '']]);
    return list;
  }

  function drawNav() {
    if (!overview) return;
    clear(nav);
    const run = overview.run;
    nav.append(h('div', { class: 'nav-head' }, h('a', { href: ctx.href({ page: 'run', run: currentRoute.run }) }, run.name),
      h('div', { class: 'muted small' }, `${overview.cells.length} planned evaluations`)));
    for (const task of run.tasks) {
      const group = h('div', { class: 'nav-task' }, h('div', { class: 'nav-task-name', title: task.id }, taskName(task.id)));
      for (const c of overview.cells.filter((x) => x.task === task.id).sort((a, b) => ARM_ORDER.indexOf(a.arm) - ARM_ORDER.indexOf(b.arm))) {
        const active = c.evaluation === currentRoute.id;
        const label = armLabel(c.arm) + (overview.cells.filter((x) => x.task === c.task && x.arm === c.arm).length > 1 ? ` · ${c.model.split('/').pop()}${c.repeat > 1 ? ' r' + c.repeat : ''}` : '');
        group.append(c.evaluation
          ? h('a', { class: ['nav-item', active && 'active'], href: ctx.href(evalRoute(c.evaluation, currentRoute.tab)), title: c.reason || '' },
            h('span', { class: ['dot', c.outcome] }), label, h('span', { class: 'r' }, c.outcome === 'credited' ? '' : c.reason || ''))
          : h('span', { class: 'nav-item muted' }, h('span', { class: ['dot', 'missing'] }), label));
      }
      nav.append(group);
    }
    const active = nav.querySelector('.active');
    if (active) active.scrollIntoView({ block: 'nearest' });
  }

  function header() {
    const n = neighbours();
    const plan = ev.plan || {};
    const spec = plan.agent_spec || {};
    const cell = overview?.cells.find((c) => c.evaluation === currentRoute.id);
    const lineageNotice = cell?.outcome === 'interrupted'
      ? callout('warn', 'stop', h('strong', null, 'Interrupted. '), 'The run stopped before this evaluation finished, so it was never graded and earns zero credit. Evidence recorded up to the interruption is shown; the controller never attested this link to the run.')
      : cell?.lineage === 'pending'
        ? callout('info', 'clock', h('strong', null, 'Lineage pending. '), 'This attempt is recorded as running. The controller attests that it belongs to this run plan only when it finishes; the link shown here is provisional.')
        : null;
    const kindNotice = ev.kind === 'fixture'
      ? callout('info', 'info', h('strong', null, 'Scripted harness fixture. '), 'Actions were programmed to exercise the harness; this is not a model result.')
      : ev.kind === 'reference' ? callout('info', 'shieldCheck', h('strong', null, 'Reference controller. '), 'The evaluated agent was bypassed and a known solution was submitted; this cohort is separate from model scores.')
        : null;
    return [h('div', { class: 'eval-head' },
      h('div', { class: 'grow' },
        h('div', { class: 'eyebrow' }, `${ev.platform} · ${ev.arm.label}`, n.total ? h('span', { class: 'muted' }, `· ${n.index + 1} of ${n.total} in run`) : null),
        h('h1', null, `${taskName(ev.task)} — ${ev.arm.label}`),
        h('div', { class: 'meta' },
          chip(ev.task, null, { mono: true, icon: 'target' }),
          chip(RUNNER_LABELS[ev.runner] || ev.runner, 'agent', { icon: 'terminal' }),
          chip(ev.model || '—', 'model', { mono: true }),
          (spec.reasoning_effort || plan.model_variant) ? chip(spec.reasoning_effort || plan.model_variant, 'effort') : null,
          plan.task_status ? chip(plan.task_status, 'task') : null,
          plan.research_core === false ? chip('not research core', null, { title: 'This task is not admitted to research scores' }) : null,
          chip(ev.path, null, { mono: true, icon: 'folder', title: 'Evaluation folder relative to the viewer root' }))),
      h('div', { class: 'nav-buttons' },
        n.prev ? h('a', { class: 'btn btn-sm', href: ctx.href(evalRoute(n.prev.evaluation, currentRoute.tab)), title: 'Previous evaluation ([)' }, icon('chevronLeft'), 'Prev') : null,
        n.next ? h('a', { class: 'btn btn-sm', href: ctx.href(evalRoute(n.next.evaluation, currentRoute.tab)), title: 'Next evaluation (])' }, 'Next', icon('chevronRight')) : null)),
    kindNotice ? h('div', { style: { marginBottom: '14px' } }, kindNotice) : null,
    lineageNotice ? h('div', { style: { marginBottom: '14px' } }, lineageNotice) : null,
    verdict()];
  }

  function verdict() {
    const cell = overview?.cells.find((c) => c.evaluation === currentRoute.id);
    const o = cell?.outcome === 'interrupted' ? 'interrupted' : ev.outcome;
    const lineIcon = { good: 'check', bad: 'x', muted: 'minus' };
    return h('div', { class: ['verdict', o, currentRoute.tab !== 'overview' && 'compact'] },
      h('div', { class: 'v-icon' }, icon(OUTCOME_ICONS[o] || 'minus')),
      h('div', null,
        h('div', { class: 'v-title' }, verdictTitle(ev, o),
          ev.row?.score !== undefined && ev.row?.score !== null ? badge(`recorded score ${ev.row.score}`, 'outline') : null,
          ev.summary?.status ? badge(`evaluation status: ${human(ev.summary.status)}`, 'outline') : null),
        h('ul', { class: 'v-lines' }, ev.verdict.map((line) => h('li', { class: line.tone }, icon(lineIcon[line.tone] || 'minus'), h('span', null, line.text))))));
  }

  function tabBar() {
    return h('nav', { class: 'tabs', 'aria-label': 'Evaluation sections' }, tabs().map(([id, label, ic, count], i) =>
      h('a', { class: currentRoute.tab === id ? 'active' : null, href: ctx.href(evalRoute(currentRoute.id, id, id === currentRoute.tab ? currentRoute.query : null)), title: `${label} (${i + 1})` },
        icon(ic), label, count && count[0] ? h('span', { class: ['count', count[1]] }, count[0]) : null)));
  }

  const tabCtx = {
    get ev() { return ev; },
    get route() { return currentRoute; },
    ctx,
    setQuery: (q) => ctx.setQuery(q),
    go: (tab, query) => ctx.navigate(evalRoute(currentRoute.id, tab, new URLSearchParams(query || {}))),
    openRecord: (path, line) => openRecord(ev.id, path, line, (p, l) => ctx.navigate(evalRoute(currentRoute.id, 'files', new URLSearchParams({ path: p, line: l })))),
    state: tabState,
  };

  async function drawTab() {
    const holder = h('div');
    // Prev/Next keep the open tab; an evaluation without that tab (a judgment has no paired execution) shows its overview.
    if (!tabs().some(([id]) => id === currentRoute.tab)) currentRoute = { ...currentRoute, tab: 'overview' };
    const tab = currentRoute.tab;
    clear(main).append(...header().filter(Boolean), tabBar(), holder);
    if (tabHandle && tabHandle.dispose) tabHandle.dispose();
    tabHandle = null;
    if (tab === 'trajectory') tabHandle = await renderTrajectory(holder, tabCtx);
    else if (tab === 'submission') tabHandle = await renderSubmission(holder, tabCtx);
    else if (tab === 'execution') tabHandle = await renderExecution(holder, tabCtx);
    else if (tab === 'task') tabHandle = await renderTask(holder, tabCtx);
    else if (tab === 'files') tabHandle = await renderFiles(holder, tabCtx);
    else renderOverview(holder, tabCtx);
  }

  async function draw() {
    const crumbs = [{ label: 'Runs', href: '#/' }];
    if (overview) crumbs.push({ label: overview.run.name, href: ctx.href({ page: 'run', run: currentRoute.run }) });
    crumbs.push({ label: `${taskName(ev.task)} · ${ev.arm.label}` });
    ctx.setCrumbs(crumbs);
    drawNav();
    await drawTab();
  }

  await draw();
  return {
    async update(next) {
      const tabChanged = next.tab !== currentRoute.tab;
      const prevQuery = currentRoute.query.toString();
      currentRoute = next;
      if (!tabChanged && tabHandle && tabHandle.update) {
        await tabHandle.update(next, prevQuery);
        return;
      }
      await drawTab();
      if (tabChanged) window.scrollTo(0, 0);
    },
    async poll() {
      const next = await api.evaluation(currentRoute.id);
      const changed = next.last_evidence !== ev.last_evidence || next.outcome !== ev.outcome || JSON.stringify(next.summary) !== JSON.stringify(ev.summary);
      if (!changed) return;
      ev = next;
      clearTrajectories(ev.id);
      if (currentRoute.run) overview = await runOverview(currentRoute.run, true);
      const y = window.scrollY;
      const following = window.innerHeight + y >= document.documentElement.scrollHeight - 120;
      await draw();
      window.scrollTo(0, following && currentRoute.tab === 'trajectory' ? document.documentElement.scrollHeight : y);
    },
    key(e) {
      if (tabHandle && tabHandle.key && tabHandle.key(e)) return;
      const n = neighbours();
      if (e.key === '[' && n.prev) ctx.navigate(evalRoute(n.prev.evaluation, currentRoute.tab));
      else if (e.key === ']' && n.next) ctx.navigate(evalRoute(n.next.evaluation, currentRoute.tab));
      else if (/^[1-6]$/.test(e.key)) {
        const list = tabs();
        const target = list[Number(e.key) - 1];
        if (target) ctx.navigate(evalRoute(currentRoute.id, target[0]));
      }
    },
    dispose() { if (tabHandle && tabHandle.dispose) tabHandle.dispose(); },
  };
}

// ---------------------------------------------------------------- overview tab
function renderOverview(root, t) {
  const ev = t.ev;
  const left = h('div', { class: 'stack-lg' });
  const right = h('div', { class: 'stack-lg' });
  left.append(h('div', { class: 'section-title' }, h('h2', null, ev.arm.family === 'judge' ? 'Trials' : 'Authoring and grading')));
  for (const trial of ev.trials) left.append(trialCard(ev, trial, t));
  const issues = allIssues(ev);
  left.append(card(`Recorded issues (${issues.length})`, issues.length ? issueList(issues, t) : h('p', { class: 'muted' }, 'No diagnostics were recorded.'),
    { icon: 'alert', flush: !!issues.length,
      foot: 'Issues are copied from failure-v1 diagnostics. "Pair-dependent" mismatches are expected on the faulty app.' }));
  right.append(card('Integrity checks', checks(ev.integrity), { icon: 'shieldCheck' }));
  right.append(card('Configuration', configuration(ev), { icon: 'code' }));
  if (ev.warnings && ev.warnings.length) {
    right.append(card('Viewer warnings', h('ul', { class: 'checks' }, ev.warnings.map((w) => h('li', { class: 'warn' }, icon('alert'),
      h('div', null, h('span', { class: 'mono small' }, w.file), h('div', { class: 'detail' }, w.message))))), { icon: 'info' }));
  }
  root.append(h('div', { class: 'grid-main' }, left, right));
}

function figure(label, value, title) {
  return h('div', { class: 'figure', title }, h('div', { class: 'l' }, label), h('div', { class: 'v' }, value));
}

function trialCard(ev, trial, t) {
  const m = trial.metrics || {};
  const stats = trial.trajectory?.stats;
  const tokens = stats?.tokens || {};
  const end = trial.trajectory?.end;
  const body = h('div', null);
  if (ev.arm.family === 'judge') {
    const graded = m.status === 'graded';
    const correct = graded && m.prediction === m.expected;
    body.append(h('div', { class: 'judgment' },
      graded ? h('span', { class: ['label', m.prediction === 'PASS' ? 'pass' : 'fail'] }, m.prediction) : h('span', { class: 'label muted' }, 'No verdict'),
      h('div', null,
        h('div', null, graded ? `Expected ${m.expected}` : m.reason || human(m.status)),
        graded ? badge(correct ? 'Correct judgment' : 'Wrong judgment', correct ? 'good' : 'bad', correct ? 'check' : 'x') : null)));
    if (trial.judgment?.reason) body.append(h('div', { class: 'label-sm', style: { marginTop: '12px' } }, 'Stated reason'), h('div', { class: 'quote' }, trial.judgment.reason));
  } else {
    body.append(h('div', { class: 'row' }, badge(human(m.status || 'not graded'), m.status === 'graded' ? 'good' : m.status ? 'warn' : ''),
      m.reward !== undefined ? badge(`reward ${m.reward}`, m.reward === 1 ? 'good' : 'bad') : null,
      trial.sealed_file ? badge(`sealed ${trial.sealed_file.split('/').pop()}`, 'outline', 'box') : badge('no sealed submission', 'bad', 'x'),
      m.reason ? h('span', { class: 'muted' }, m.reason) : null));
  }
  body.append(h('div', { class: 'figures' },
    figure('Agent time', seconds(trial.agent?.elapsed_seconds)),
    figure('Tool calls', formatNumber(stats?.tool_calls)),
    figure('Failed calls', formatNumber((stats?.failed_tools || 0) + (stats?.blocked || 0)), 'Denied, failed or blocked tool requests'),
    figure('Screenshots', formatNumber(stats?.screenshots)),
    figure('Tokens in / out', tokens.input !== undefined ? `${compact(tokens.input)} / ${compact(tokens.output)}` : '—',
      tokens.cached_input ? `${formatNumber(tokens.cached_input)} cached input tokens` : null)));
  if (end) {
    const ok = end.status === 'completed';
    body.append(h('div', { class: 'row', style: { marginBottom: '8px' } },
      badge(ok ? 'Agent finished normally' : `Agent session ${end.status}`, ok ? 'good' : 'bad', ok ? 'flag' : 'stop'),
      end.finish_reason ? chip(end.finish_reason, 'finish') : null,
      trial.agent?.shutdown_reason && trial.agent.shutdown_reason !== 'completed' ? chip(trial.agent.shutdown_reason, 'shutdown') : null));
  } else if (!trial.trajectory?.available) {
    body.append(h('p', { class: 'muted' }, ev.kind === 'reference' ? 'No agent trajectory: the reference controller bypassed the agent.' : 'No agent trajectory was recorded for this trial.'));
  }
  if (stats?.final_message) body.append(h('div', { class: 'label-sm' }, 'Final agent message'), h('div', { class: 'quote' }, stats.final_message));
  for (const w of trial.trajectory?.warnings || []) body.append(h('p', { class: 'muted small', style: { marginTop: '8px' } }, icon('info'), ' ', w));
  const actions = h('div', { class: 'row' },
    trial.trajectory?.available ? h('button', { class: 'btn btn-sm', type: 'button', onclick: () => t.go('trajectory', { trial: trial.id }) }, icon('list'), 'Trajectory') : null,
    h('button', { class: 'btn btn-sm', type: 'button', onclick: () => t.go('files', { path: trial.metrics_path }) }, icon('file'), 'Metrics'));
  return card(trialLabel(ev, trial), body, { icon: ev.arm.family === 'judge' ? 'eye' : 'pen', actions,
    foot: h('span', { class: 'mono' }, `trial ${trial.id}`) });
}

function issueList(issues, t) {
  return h('div', { class: 'issue-list' }, issues.map((issue) => {
    const impact = IMPACT[issue.impact];
    return h('div', { class: ['issue', issue.impact] }, icon(issue.impact === 'zero_credit' ? 'x' : 'alert'),
      h('div', null,
        h('div', { class: 'msg' }, issue.message || human(issue.cause)),
        causeText(issue.cause) && causeText(issue.cause) !== issue.message ? h('div', { class: 'explain' }, causeText(issue.cause)) : null,
        causeHint(issue.cause) ? h('div', { class: 'explain' }, causeHint(issue.cause)) : null,
        h('div', { class: 'where' }, chip(issue.where, null, { icon: 'target' }), issue.cause ? chip(issue.cause, 'cause', { mono: true }) : null,
          issue.operations.map((op) => chip(op, 'op', { mono: true })),
          (issue.underlying_causes || []).map((u) => chip(u, 'underlying', { mono: true })))),
      h('div', { class: 'stack', style: { alignItems: 'flex-end', gap: '6px' } },
        impact ? badge(impact.label, impact.tone) : null,
        issue.sourceLink ? h('button', { class: 'raw-link', type: 'button', onclick: () => t.openRecord(issue.sourceLink.path, issue.sourceLink.line) },
          icon('file'), `${issue.sourceLink.path.split('/').pop()}${issue.sourceLink.line ? ':' + issue.sourceLink.line : ''}`) : null));
  }));
}

function checks(list) {
  const ic = { pass: 'check', fail: 'x', warn: 'alert', unknown: 'minus' };
  return h('ul', { class: 'checks' }, list.map((c) => h('li', { class: c.status }, icon(ic[c.status] || 'minus'),
    h('div', null, c.label, c.detail ? h('div', { class: 'detail' }, c.detail) : null))));
}

function configuration(ev) {
  const p = ev.plan || {};
  const spec = p.agent_spec || {};
  const trial = ev.trials[0] || {};
  const budgets = trial.agent?.budgets;
  const box = h('div', { class: 'stack' }, kv([
    ['Arm', `${ev.arm.label} (${ev.arm.id})`],
    ['What the arm does', ev.arm.summary],
    ['Agent runner', `${RUNNER_LABELS[ev.runner] || ev.runner}${p.runner_version ? ' ' + p.runner_version : ''}${trial.agent?.opencode_version ? ' ' + trial.agent.opencode_version : ''}`],
    ['Model', ev.model, true],
    ['Reasoning effort', spec.reasoning_effort || p.model_variant],
    ['Auth / billing', [spec.auth_mode, trial.agent?.billing_mode].filter(Boolean).join(' · ') || undefined],
    ['Tool profile', spec.tool_profile, true],
    ['Budget profile', spec.budget_profile, true],
    ['Domain', p.domain || ev.platform],
    ['Contracts', [p.action_contract, p.failure_contract, p.environment_contract].filter(Boolean).join(', ') || undefined, true],
    ['Task status', p.task_status],
    ['Research core', p.research_core === undefined ? undefined : String(p.research_core)],
    ['Planned trials', p.planned_trials],
    ['Plan hash', p.resolved_plan_sha256 ? shortHash(p.resolved_plan_sha256, 16) : undefined, true],
    ['Configuration hash', p.configuration_sha256 ? shortHash(p.configuration_sha256, 16) : undefined, true],
    ['Known cost', ev.cost?.known_usd !== null && ev.cost?.known_usd !== undefined ? `$${ev.cost.known_usd.toFixed(4)}` : 'unknown (not recorded)'],
  ]));
  if (budgets) box.append(h('details', null, h('summary', { class: 'muted small' }, 'Budgets'), jsonView(budgets)));
  box.append(h('details', null, h('summary', { class: 'muted small' }, 'Full plan record'), jsonView(p)));
  return box;
}

// ---------------------------------------------------------------- task tab
async function renderTask(root, t) {
  const ev = t.ev;
  const grid = h('div', { class: 'grid-main' });
  const left = h('div', { class: 'stack-lg' });
  const right = h('div', { class: 'stack-lg' });
  left.append(card('Public instruction given to the agent', ev.instruction ? markdown(ev.instruction.text)
    : empty('No public instruction was recorded.'), { icon: 'message', foot: ev.instruction ? `${ev.instruction.path} · ${bytes(ev.instruction.size)}` : null }));
  if (ev.steps && Array.isArray(ev.steps)) {
    left.append(card('Journey steps supplied to the agent', h('ol', { class: 'md' }, ev.steps.map((s) => h('li', null, typeof s === 'string' ? s : JSON.stringify(s)))), { icon: 'list' }));
  }
  if (ev.test_source) {
    left.append(card('Public test source (read-only for the judge)', codeView(ev.test_source.text, { lang: 'python' }), { icon: 'code', foot: ev.test_source.path }));
  }
  right.append(card('About this arm', h('div', { class: 'stack' }, h('p', null, ev.arm.summary),
    kv([['Family', human(ev.arm.family)], ['Evidence', human(ev.arm.evidence)], ['Submission', ev.arm.artifact, true],
      ['Paired grading', ev.arm.family === 'judge' ? 'Judged once on the correct state and once on the faulty state; both must be right.'
        : 'Executed against the correct app and the faulty app; it must pass on the correct app and fail behaviorally on the faulty app.']])), { icon: 'info' }));
  const trajectories = {};
  await Promise.all(ev.trials.map(async (trial) => {
    if (trial.trajectory?.available) {
      try { trajectories[trial.id] = await loadTrajectory(ev.id, trial.id); } catch { /* shown as unknown */ }
    }
  }));
  for (const trial of ev.trials) {
    right.append(inputsCard(ev, trial, trajectories[trial.id], t));
  }
  grid.append(left, right);
  root.append(grid);
}

function readSteps(traj, name) {
  if (!traj) return [];
  const target = `/workspace/${name}`;
  return traj.steps.filter((s) => s.kind === 'tool' && s.status === 'ok' && ['bench_read_file', 'bench_read_image', 'read'].includes(s.tool)
    && (s.arguments?.path === target || s.arguments?.filePath === target));
}

function inputsCard(ev, trial, traj, t) {
  const inputs = trial.inputs || [];
  if (!inputs.length) return card(`Inputs · ${trialShort(ev, trial)}`, empty('No materialized workspace inputs were recorded.'), { icon: 'folder' });
  const images = inputs.filter((i) => i.image);
  const files = inputs.filter((i) => !i.image);
  const body = h('div', { class: 'stack' });
  const readBadge = (input) => {
    const reads = readSteps(traj, input.name);
    if (!traj) return badge('read status unknown', 'outline');
    return reads.length ? h('button', { class: 'badge good', type: 'button', onclick: () => t.go('trajectory', { trial: trial.id, step: reads[0].index }),
      title: 'Open the step where the agent read this file' }, icon('eye'), `read at step ${reads.map((r) => r.index).join(', ')}`)
      : badge('not read by the agent', 'outline');
  };
  for (const input of files) {
    body.append(h('div', { class: 'row-between' }, h('span', { class: 'mono small' }, input.name),
      h('span', { class: 'row' }, input.hash_matches === false ? badge('hash mismatch', 'bad') : input.present ? null : badge('missing', 'bad'), readBadge(input))));
  }
  if (images.length) {
    body.append(h('div', { class: 'label-sm', style: { marginTop: '6px' } }, `Screenshots offered (${images.length})`));
    const grid = h('div', { class: 'shot-row' });
    images.forEach((input) => {
      grid.append(h('div', { class: 'stack', style: { gap: '4px', maxWidth: '200px' } },
        input.present ? shot(artifactUrl(ev.id, input.path), { small: true, caption: input.name.split('/').pop(), alt: input.name }) : empty('missing'),
        readBadge(input)));
    });
    body.append(grid);
  }
  return card(`Inputs · ${trialShort(ev, trial)}`, body, { icon: 'folder',
    foot: 'Offered inputs are what the agent could read; a read call is shown only when the trajectory records it.' });
}
