// Submission (sealed judgment / program / references) and paired execution evidence.
import { artifactUrl } from './api.js';
import { badge, callout, card, chip, codeView, empty, h, icon, jsonView, kv, lightbox, shot } from './dom.js';
import { alignTimelines, bytes, causeHint, causeText, formatNumber, human, seconds, shortHash } from './format.js';
import { loadTrajectory } from './trajectory.js';

const EXPECTED = { correct: 'PASS', faulty: 'BEHAVIOR_FAIL' };

function outcomeTone(variant, outcome) {
  if (!outcome) return 'warn';
  if (outcome === EXPECTED[variant]) return 'pass';
  if (outcome === 'ERROR' || outcome === 'SETUP_ERROR') return 'warn';
  return 'bad';
}

function sessionEnd(trial) {
  const end = trial.trajectory?.end;
  const stats = trial.trajectory?.stats;
  if (!end) return h('p', { class: 'muted' }, 'No agent trajectory was recorded.');
  const writes = stats?.by_tool ? (stats.by_tool.bench_write_file || 0) + (stats.by_tool.write || 0) + (stats.by_tool.edit || 0) : 0;
  return h('div', { class: 'stack', style: { gap: '8px' } },
    h('div', { class: 'row' }, badge(end.status === 'completed' ? 'Agent finished normally' : `Agent session ${end.status}`, end.status === 'completed' ? 'outline' : 'bad', 'flag'),
      chip(`${formatNumber(stats?.tool_calls)} tool calls`, null), chip(`${writes} write calls`, null)),
    stats?.final_message ? h('div', null, h('div', { class: 'label-sm' }, 'Final agent message'), h('div', { class: 'quote' }, stats.final_message)) : null);
}

function hashBadge(matches) {
  if (matches === true) return badge('hash verified', 'good', 'check', 'Bytes on disk match the recorded SHA-256');
  if (matches === false) return badge('hash mismatch', 'bad', 'x');
  return badge('hash not checked', 'outline');
}

// ---------------------------------------------------------------- submission tab
export async function renderSubmission(root, t) {
  const ev = t.ev;
  const wrap = h('div', { class: 'stack-lg' });
  if (ev.arm.family === 'judge') {
    const grid = h('div', { class: 'grid-2' });
    for (const trial of ev.trials) grid.append(judgmentCard(ev, trial, t));
    wrap.append(grid);
  } else {
    const trial = ev.trials[0];
    if (!trial) { root.append(empty('No trial was recorded.')); return {}; }
    await programView(wrap, ev, trial, t);
  }
  root.append(wrap);
  return {
    update(route) {
      const line = Number(route.query.get('line'));
      if (line) scrollToLine(root, line);
    },
  };
}

function judgmentCard(ev, trial, t) {
  const m = trial.metrics || {};
  const label = trial.variant === 'faulty' ? 'Faulty-state recording' : 'Correct-state recording';
  const body = h('div', { class: 'stack' });
  if (!trial.sealed_file) {
    body.append(callout('bad', 'x', h('strong', null, 'No judgment was sealed. '), m.reason || 'The agent did not write /workspace/output/judgment.json.'));
    body.append(sessionEnd(trial));
  } else {
    const verdict = trial.judgment?.verdict;
    const correct = m.status === 'graded' && m.prediction === m.expected;
    body.append(h('div', { class: 'judgment' }, h('span', { class: ['label', verdict === 'PASS' ? 'pass' : 'fail'] }, verdict || '—'),
      h('div', null, h('div', null, m.expected ? `Expected ${m.expected}` : 'Expected label not graded'),
        m.status === 'graded' ? badge(correct ? 'Correct judgment' : 'Wrong judgment', correct ? 'good' : 'bad', correct ? 'check' : 'x') : badge(human(m.status), 'warn'))));
    if (trial.judgment?.reason) body.append(h('div', { class: 'label-sm' }, 'Stated reason'), h('div', { class: 'quote' }, trial.judgment.reason));
    body.append(h('div', { class: 'row' }, hashBadge(trial.sealed_hash_matches), chip(shortHash(trial.submission?.sha256, 16), 'sha256', { mono: true })));
    body.append(h('details', null, h('summary', { class: 'muted small' }, 'Sealed judgment.json'), jsonView(trial.sealed_text?.text || '')));
  }
  return card(label, body, { icon: 'eye', actions: h('button', { class: 'btn btn-sm', type: 'button', onclick: () => t.go('trajectory', { trial: trial.id }) }, icon('list'), 'Trajectory') });
}

async function programView(wrap, ev, trial, t) {
  const m = trial.metrics || {};
  if (!trial.sealed_file) {
    wrap.append(callout('bad', 'x', h('strong', null, 'No program was sealed. '), m.reason || `The agent did not write ${ev.arm.artifact}.`,
      trial.draft_files?.length ? ` Draft copies found: ${trial.draft_files.join(', ')}.` : ''));
    wrap.append(card('How the authoring session ended', sessionEnd(trial), { icon: 'flag' }));
    return;
  }
  const highlight = {};
  const titles = {};
  for (const e of trial.executions) {
    for (const line of e.traceback_lines || []) {
      highlight[line] = 'hl';
      titles[line] = `${titles[line] ? titles[line] + '; ' : ''}Traceback in the ${e.variant} app execution`;
    }
  }
  const text = trial.sealed_text?.text || '';
  const source = text.split('\n');
  source.forEach((line, i) => {
    if (!line.includes('expect_image(')) return;
    const ref = /expect_image\(\s*["']([^"']+)["']/.exec(line) || /^\s*["']([^"']+)["']/.exec(source[i + 1] || '');
    if (ref && !highlight[i + 1]) { highlight[i + 1] = 'note'; titles[i + 1] = `Reference image “${ref[1]}”`; }
  });
  const lines = text.split('\n').length;
  const name = trial.sealed_file.split('/').pop();
  const failing = Object.keys(highlight).filter((k) => highlight[k] === 'hl');
  wrap.append(card(`Sealed ${name}`, h('div', { class: 'stack' },
    h('div', { class: 'row' }, hashBadge(trial.sealed_hash_matches), chip(shortHash(trial.submission?.sha256, 16), 'sha256', { mono: true }),
      chip(`${lines} lines · ${bytes(trial.sealed_text?.size)}`, null),
      failing.length ? badge(`traceback at line ${failing.join(', ')}`, 'bad', 'alert') : null,
      trial.submission?.references_sha256 ? chip(shortHash(trial.submission.references_sha256, 12), 'references', { mono: true }) : null),
    codeView(text, { lang: 'python', highlight, titles, idPrefix: 'code-line-', tall: true })),
  { icon: 'code', foot: 'This is the exact sealed artifact that was executed. Red lines appear in an execution traceback; blue lines reference a sealed image.' }));

  const refs = trial.references || [];
  if (refs.length) {
    let traj = null;
    try { traj = trial.trajectory?.available ? await loadTrajectory(ev.id, trial.id) : null; } catch { traj = null; }
    const bySha = new Map();
    for (const s of traj?.steps || []) for (const image of s.images || []) if (!bySha.has(image.sha256)) bySha.set(image.sha256, s);
    const grid = h('div', { class: 'shot-row' });
    for (const ref of refs) {
      const step = bySha.get(ref.actual_sha256);
      grid.append(h('div', { class: 'card card-pad stack', style: { gap: '8px', maxWidth: '360px' } },
        h('div', { class: 'row-between' }, h('strong', null, ref.name), hashBadge(ref.hash_matches)),
        shot(artifactUrl(ev.id, ref.file), { small: true, caption: ref.name, alt: `Reference ${ref.name}` }),
        step ? h('button', { class: 'btn btn-sm', type: 'button', onclick: () => t.go('trajectory', { trial: trial.id, step: step.index }) },
          icon('camera'), `Captured at trajectory step ${step.index}`)
          : h('span', { class: 'muted small' }, 'No identical screenshot found in the authoring trajectory.')));
    }
    wrap.append(card(`Sealed reference images (${refs.length})`, grid, { icon: 'image',
      foot: 'References were frozen before paired execution. A capture link means the exact bytes appear in an authoring observation.' }));
  }
  if (trial.draft_files?.length) {
    wrap.append(card('Retained output copies', h('div', { class: 'stack' },
      h('p', { class: 'muted' }, 'Copies left in the output directory. They are untrusted drafts, not proof of what executed.'),
      h('div', { class: 'row' }, trial.draft_files.map((p) => h('button', { class: 'btn btn-sm', type: 'button', onclick: () => t.go('files', { path: p }) }, icon('file'), p)))),
    { icon: 'folder' }));
  }
  const line = Number(t.route.query.get('line'));
  if (line) requestAnimationFrame(() => scrollToLine(wrap, line));
}

function scrollToLine(root, line) {
  const row = root.querySelector(`#code-line-${line}`) || document.getElementById(`code-line-${line}`);
  if (row) row.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

// ---------------------------------------------------------------- execution tab
export async function renderExecution(root, t) {
  const ev = t.ev;
  const trial = ev.trials[0];
  const executions = trial?.executions || [];
  if (!executions.length) {
    const m = trial?.metrics || {};
    root.append(callout('warn', 'alert', h('strong', null, 'No paired execution was recorded. '),
      m.reason || 'The program was not executed, usually because authoring failed or no submission was sealed.'));
    return {};
  }
  // Each version is executed several times; compare one aligned run at a time.
  const runs = { correct: executions.filter((e) => e.variant === 'correct'), faulty: executions.filter((e) => e.variant === 'faulty') };
  const count = Math.max(runs.correct.length, runs.faulty.length);
  const credited = (i) => runs.correct[i]?.outcome === 'PASS' && runs.faulty[i]?.outcome === 'BEHAVIOR_FAIL';
  const requested = Number.parseInt(t.route.query.get('run') || '', 10);
  let index = Number.isInteger(requested) && requested >= 1 && requested <= count ? requested - 1 : -1;
  if (index < 0) index = Math.max(0, [...Array(count).keys()].find((i) => !credited(i)) ?? 0);
  const byVariant = { correct: runs.correct[index], faulty: runs.faulty[index] };
  const correct = byVariant.correct;
  const faulty = byVariant.faulty;
  const wrap = h('div', { class: 'stack-lg' });
  if (count > 1) wrap.append(card('Repeated executions', repetitionTable(runs, count, index, t), { icon: 'list', flush: true,
    foot: 'Credit requires every correct-app run to pass and every faulty-app run to fail behaviorally. Select a run to compare it below.' }));
  wrap.append(h('div', { class: 'exec-heads' }, ['correct', 'faulty'].map((v) => execHead(byVariant[v], v, t))));
  wrap.append(card('Step-by-step comparison', alignment(correct, faulty, t), { icon: 'beaker', flush: true,
    foot: 'Rows are aligned by position in each execution log. Highlighted rows differ between the two runs; the first one is where behavior diverged.' }));
  const imageCards = assertionImages(ev, correct, faulty);
  if (imageCards.length) {
    wrap.append(h('div', { class: 'section-title' }, h('h2', null, 'Image assertions'),
      h('span', { class: 'muted small' }, 'Expected = sealed reference crop · Actual = live capture crop · Diff = differing pixels')));
    wrap.append(...imageCards);
  }
  for (const e of executions) {
    if (e.stderr && e.stderr.text.trim()) wrap.append(stderrCard(e, t));
  }
  root.append(wrap);
  const focus = t.route.query.get('assert');
  if (focus) requestAnimationFrame(() => document.getElementById(`assert-${focus}`)?.scrollIntoView({ block: 'start' }));
  const shownRun = t.route.query.get('run') || '';
  let replacement = null;
  return {
    async update(route, previous) {
      if (replacement) return replacement.update(route, previous);
      if ((route.query.get('run') || '') !== shownRun) {
        root.replaceChildren();
        replacement = await renderExecution(root, t);
        return undefined;
      }
      const a = route.query.get('assert');
      if (a) document.getElementById(`assert-${a}`)?.scrollIntoView({ block: 'start', behavior: 'smooth' });
    },
  };
}

function repetitionTable(runs, count, selected, t) {
  const table = h('table', { class: 'table' });
  table.append(h('thead', null, h('tr', null, h('th', null, 'Run'), h('th', null, 'Correct app'), h('th', null, 'Faulty app'), h('th', null, ''))));
  const body = h('tbody');
  for (let i = 0; i < count; i += 1) {
    const cell = (variant) => {
      const e = runs[variant][i];
      return h('td', null, e ? h('span', { class: ['o', outcomeTone(variant, e.outcome)] }, e.outcome || 'No outcome') : h('span', { class: 'muted small' }, 'not run'));
    };
    body.append(h('tr', { class: i === selected ? 'selected' : null }, h('td', null, String(i + 1)), cell('correct'), cell('faulty'),
      h('td', null, i === selected ? h('span', { class: 'muted small' }, 'shown below')
        : h('button', { class: 'btn btn-sm', type: 'button', onclick: () => t.go('execution', { run: String(i + 1) }) }, 'Compare'))));
  }
  table.append(body);
  return table;
}

function execHead(e, variant, t) {
  if (!e) return h('div', { class: 'card exec-head' }, h('div', { class: 'label-sm' }, `${human(variant)} app`), empty('No execution recorded.'));
  const assertions = e.assertions || [];
  const matched = assertions.filter((a) => a.matched).length;
  const tone = outcomeTone(variant, e.outcome);
  return h('div', { class: 'card exec-head stack', style: { gap: '8px' } },
    h('div', { class: 'row-between' }, h('div', { class: 'label-sm' }, `${human(variant)} app`), chip(e.id, 'execution', { mono: true })),
    h('div', { class: ['o', tone] }, e.outcome || 'No outcome'),
    h('div', { class: 'expect' }, `A credited program must record ${EXPECTED[variant]} here.`),
    kv([['Assertions matched', `${matched} / ${assertions.length}`], ['Actions performed', formatNumber(e.actions)],
      ['Elapsed', seconds(e.elapsed_seconds)], ['Exit code', e.exit_code ?? '—']]),
    e.issues.filter((i) => i.impact === 'zero_credit').map((i) => h('div', { class: 'failure-box' }, icon('alert'),
      h('div', null, i.message, h('div', { class: 'muted small' }, causeHint(i.cause) || causeText(i.cause) || '')))),
    h('div', { class: 'row' }, Object.entries(e.files).map(([name, path]) => h('button', { class: 'btn btn-sm', type: 'button',
      onclick: () => t.go('files', { path }) }, icon('file'), name))));
}

function timelineCell(row, e, t) {
  if (!row) return h('span', { class: 'muted small' }, '— no record —');
  const ic = { ok: 'check', mismatch: 'x', error: 'alert', denied: 'shield', warning: 'alert', info: 'minus' }[row.status] || 'minus';
  const tone = row.kind === 'environment' ? 'env' : row.status;
  const image = row.image;
  const browser = e && e.files['browser.log'];
  return h('div', { class: ['tl', tone] }, icon(row.kind === 'action' ? 'pointer' : row.kind === 'environment' ? 'info' : ic),
    h('div', { class: 'grow' },
      h('span', null, row.text),
      row.precondition ? h('span', { class: 'pre', title: 'Authored precondition' }, 'precondition') : null,
      row.kind === 'assertion' && row.status === 'mismatch' ? h('span', { class: 'pre', style: { color: 'var(--bad)' } }, 'mismatch') : null,
      image && image.different_pixels !== undefined ? h('div', { class: 'px' },
        `${formatNumber(image.different_pixels)} of ${formatNumber(image.compared_pixels)} pixels differ`,
        row.assertion?.max_diff_pixels !== undefined ? ` (limit ${formatNumber(row.assertion.max_diff_pixels)})` : '',
        image.directory ? ' · ' : '', image.directory ? h('a', { href: '#', onclick: (ev) => { ev.preventDefault(); t.setQuery({ assert: image.directory }); } }, `images ${image.directory}`) : null) : null,
      row.cause ? h('div', { class: 'px' }, row.cause, row.underlying ? ` (underlying: ${row.underlying.join(', ')})` : '') : null),
    browser ? h('button', { class: 'raw-link', type: 'button', title: 'Open the original log record', onclick: () => t.openRecord(browser, row.line) }, `L${row.line}`) : null);
}

function alignment(correct, faulty, t) {
  const { rows, firstDivergence } = alignTimelines(correct?.timeline, faulty?.timeline);
  const table = h('table', { class: 'align' }, h('thead', null, h('tr', null, h('th', { class: 'n' }, '#'),
    h('th', null, `Correct app · ${correct?.outcome || '—'}`), h('th', null, `Faulty app · ${faulty?.outcome || '—'}`))));
  const body = h('tbody');
  rows.forEach((r, i) => {
    const env = (r.left || r.right)?.kind === 'environment';
    body.append(h('tr', { class: [r.differs && 'diverge', env && 'env'], title: i === firstDivergence ? 'First divergence between the two executions' : null },
      h('td', { class: 'n' }, i === firstDivergence ? '▶ ' + r.index : r.index),
      h('td', null, timelineCell(r.left, correct, t)), h('td', null, timelineCell(r.right, faulty, t))));
  });
  table.append(body);
  return h('div', { class: 'table-wrap' }, table);
}

function assertionImages(ev, correct, faulty) {
  const dirs = new Set();
  for (const e of [correct, faulty]) for (const image of e?.images || []) dirs.add(image.directory);
  const cards = [];
  for (const dir of [...dirs].sort()) {
    const sides = [['correct', correct], ['faulty', faulty]].map(([variant, e]) => [variant, e, (e?.images || []).find((i) => i.directory === dir)]);
    const any = sides.find(([, , image]) => image)?.[2];
    const assertion = any?.result?.assertion || {};
    const head = h('div', { class: 'row' }, h('strong', null, `#${dir}`), h('span', null, `reference “${assertion.reference}”`),
      assertion.region ? chip(JSON.stringify(assertion.region), 'region', { mono: true }) : null,
      assertion.threshold !== undefined ? chip(String(assertion.threshold), 'threshold', { mono: true }) : null,
      assertion.max_diff_pixels !== undefined ? chip(formatNumber(assertion.max_diff_pixels), 'max diff px', { mono: true }) : null,
      assertion.masks?.length ? chip(`${assertion.masks.length} masks`, null) : null,
      assertion.precondition ? badge('precondition', 'outline') : null);
    const columns = h('div', { class: 'grid-2' }, sides.map(([variant, e, image]) => assertionSide(ev, variant, e, image)));
    cards.push(h('section', { class: 'card assert-card', id: `assert-${dir}` }, h('div', { class: 'card-head' }, head), h('div', { class: 'card-body' }, columns)));
  }
  return cards;
}

function assertionSide(ev, variant, e, image) {
  if (!image) return h('div', null, h('div', { class: 'label-sm' }, `${human(variant)} app`), empty('This assertion was not reached in this execution.'));
  const r = image.result || {};
  const url = (name) => (image.files[name] ? artifactUrl(ev.id, image.files[name]) : null);
  const gallery = ['expected.png', 'actual.png', 'diff.png', 'capture.png'].filter((n) => url(n)).map((n) => ({
    src: url(n), caption: `${human(variant)} app · #${image.directory} · ${n.replace('.png', '')}`, region: n === 'capture.png' ? r.assertion?.region : null }));
  const open = (name) => lightbox.open(gallery, Math.max(0, gallery.findIndex((g) => g.src === url(name))));
  const fig = (name, label) => (url(name) ? h('figure', null, h('figcaption', null, label), h('img', { src: url(name), alt: `${label} ${image.directory}`, loading: 'lazy', onclick: () => open(name) })) : null);
  const side = h('div', { class: 'compare' },
    h('div', { class: 'row-between' }, h('div', { class: 'label-sm' }, `${human(variant)} app`),
      r.matched ? badge('matched', 'good', 'check') : badge('mismatch', 'bad', 'x')),
    h('div', { class: 'muted small' }, `${formatNumber(r.different_pixels)} of ${formatNumber(r.compared_pixels)} pixels differ`),
    h('div', { class: 'compare-grid' }, fig('expected.png', 'Expected'), fig('actual.png', 'Actual'), fig('diff.png', 'Diff')));
  if (url('expected.png') && url('actual.png')) side.append(h('details', null, h('summary', { class: 'muted small' }, 'Swipe compare expected ↔ actual'), swipe(url('expected.png'), url('actual.png'))));
  if (url('capture.png')) side.append(h('details', null, h('summary', { class: 'muted small' }, 'Full live capture with the compared region'),
    shot(url('capture.png'), { small: true, region: r.assertion?.region, caption: 'capture', onopen: () => open('capture.png') })));
  return side;
}

function swipe(expected, actual) {
  const base = h('img', { src: actual, alt: 'Actual' });
  const topImg = h('img', { src: expected, alt: 'Expected' });
  const top = h('div', { class: 'top' }, topImg);
  const handle = h('div', { class: 'handle' });
  const box = h('div', { class: 'swipe' }, base, top, handle);
  const set = (pct) => { top.style.width = `${pct}%`; handle.style.left = `${pct}%`; };
  const size = () => { topImg.style.width = `${base.clientWidth}px`; };
  base.addEventListener('load', size);
  new ResizeObserver(size).observe(base);
  box.append(h('input', { type: 'range', min: '0', max: '100', value: '50', 'aria-label': 'Swipe position', oninput: (e) => set(e.target.value) }));
  set(50);
  return h('div', { class: 'stack', style: { gap: '4px' } }, h('div', { class: 'muted small' }, 'Left of the line: expected · right: actual'), box);
}

function stderrCard(e, t) {
  const text = e.stderr.text;
  const highlight = {};
  text.split('\n').forEach((line, i) => { if (/File "\/artifact\//.test(line) || /^\w*(Error|Exception)/.test(line)) highlight[i + 1] = 'hl'; });
  return card(`${human(e.variant)} app · stderr`, h('div', { class: 'stack' },
    e.traceback_lines?.length ? h('div', { class: 'row' }, e.traceback_lines.map((n) => h('button', { class: 'btn btn-sm', type: 'button',
      onclick: () => t.go('submission', { line: n }) }, icon('code'), `Show line ${n} in the program`))) : null,
    codeView(text, { highlight })), { icon: 'terminal', foot: e.stderr.complete ? e.stderr.path : `${e.stderr.path} · preview of the first 2 MB; open Files for the complete log` });
}
