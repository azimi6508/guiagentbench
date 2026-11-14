// Pure formatting and classification helpers. No DOM access: tested under Node.

export const ARM_ORDER = ['judge_visual', 'judge_test', 'oracle_visual', 'oracle_ui', 'test_visual', 'test_ui'];
export const ARM_LABELS = {
  judge_visual: 'Visual judge', judge_test: 'Test judge', oracle_visual: 'Visual oracle',
  oracle_ui: 'UI oracle', test_visual: 'Visual test', test_ui: 'UI test',
};

export const OUTCOMES = {
  credited: { label: 'Credited', tone: 'good', description: 'Paired reward 1 recorded.' },
  zero: { label: 'Zero credit', tone: 'bad', description: 'The model earned no credit: a wrong result, or an invalid result it caused (for example no submission).' },
  error: { label: 'Error', tone: 'warn', description: 'A framework, environment, provider or unclassified failure; zero credit and needs review.' },
  interrupted: { label: 'Interrupted', tone: 'warn', description: 'The run stopped before this evaluation finished; zero credit, no retry.' },
  running: { label: 'Running', tone: 'info', description: 'Recorded as running; this does not prove the process is alive.' },
  unpaired: { label: 'Unpaired', tone: 'muted', description: 'Single-state result; no paired score.' },
  unresolved: { label: 'Unresolved', tone: 'muted', description: 'No final paired score was recorded.' },
  missing: { label: 'Not recorded', tone: 'muted', description: 'Planned but no evidence is available.' },
};

// Plain-language meaning of failure-v1 causes, plus where to look next.
export const CAUSES = {
  app_scope_lost: ['The app left the permitted interaction scope.', 'Look at the last actions before the failure in the trajectory.'],
  policy_violation: ['A forbidden capability was requested.', 'For visual arms this often means a UI-structure query or script evaluation was used.'],
  invalid_arguments: ['A request did not match the public API contract.', 'Check the arguments of the failing call; underlying causes may be listed.'],
  target_unavailable: ['The requested target was unavailable or not uniquely actionable.', 'This does not establish whether the model, app or environment is responsible.'],
  action_timeout: ['An operation timed out; the underlying reason is unknown.', 'Inspect the screenshots around the timeout.'],
  app_not_ready: ['The application did not become ready.', 'Environment readiness issue; check app and setup logs.'],
  reset_failure: ['A requested reset did not complete.', 'Check environment events in the execution log.'],
  infrastructure_error: ['A runtime or transport operation failed.', 'Infrastructure problem; not evidence about the model.'],
  unknown_operation_error: ['An operation failed for an unclassified reason.', 'Needs manual review of the source records.'],
  provider_timeout: ['The inference provider timed out.', 'Provider-side; check inference diagnostics.'],
  provider_rate_limit: ['The inference provider reported a rate limit.', 'Provider-side; no automatic retry was made.'],
  provider_error: ['The inference provider reported an error.', 'Provider-side; check inference diagnostics.'],
  provider_transport_error: ['The connection to the inference provider failed.', 'Provider-side transport problem.'],
  capability_unavailable: ['The required tool configuration was unavailable.', 'For Codex, look for blocked policy hooks or a harness interrupt near the end of the trajectory.'],
  budget_exhausted: ['A request or model budget was exhausted.', 'Compare tool-call and token counts with the budgets in Configuration.'],
  evidence_overflow: ['The evidence limit was exceeded; partial evidence is not admitted.', 'Very large observations or outputs.'],
  context_overflow: ['The context or output limit was exceeded.', 'Check token usage near the end of the trajectory.'],
  execution_timeout: ['The execution time limit was exceeded.', 'The generated program did not finish in time.'],
  resource_limit: ['An execution resource limit was exceeded.', 'Memory, process or output limits.'],
  process_error: ['The generated program exited unsuccessfully.', 'Read the traceback in Execution; it usually follows another failure.'],
  incomplete_trajectory: ['The agent did not record a normal completion.', 'Look at how the trajectory ends: interrupts, stream errors or missing turn completion.'],
  missing_submission: ['No submission was produced.', 'The agent never wrote the required output file (or wrote it elsewhere).'],
  malformed_submission: ['The submission does not meet the artifact contract.', 'Inspect the submitted file in Submission.'],
  failed_precondition: ['An authored precondition did not match.', 'This alone does not establish an environment failure; compare with the reference images.'],
  behavioral_mismatch: ['A behavioral assertion did not match.', 'Expected on the faulty app; a problem only when it happens on the correct app.'],
  missing_checks: ['Required preconditions, assertions or journey actions are absent.', 'Inspect the submitted program.'],
  incomparable_pair: ['The executions do not have comparable definitions.', 'Compare the aligned execution timelines.'],
  unstable_execution: ['Repeated executions on the same version disagree.', 'Compare the repeated execution outcomes and timelines.'],
  legacy_ambiguous_denial: ['A historical denial that does not distinguish policy from operation failure.', 'Historical record; meaning is ambiguous.'],
  permission_rule: ['Blocked by the runner permission rules.', 'OpenCode refused the call before it reached a tool.'],
  unavailable_tool: ['The requested tool is not available in this arm.', 'The model attempted a tool outside its allowlist.'],
};

export const IMPACT = {
  zero_credit: { label: 'Zero credit', tone: 'bad' },
  pair_dependent: { label: 'Pair-dependent', tone: 'warn' },
};

export function human(value) {
  if (value === null || value === undefined || value === '') return '—';
  const text = String(value).replaceAll('_', ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function armLabel(arm) { return ARM_LABELS[arm] || human(arm); }

export function causeText(cause) { return (CAUSES[cause] || [])[0] || null; }
export function causeHint(cause) { return (CAUSES[cause] || [])[1] || null; }

export function classify(record, attemptStatus) {
  if (attemptStatus === 'interrupted') return 'interrupted';
  if (!record) return 'missing';
  if (record.status === 'running' || record.status === 'incomplete') return 'running';
  const invalid = record.invalid_or_missing;
  if (attemptStatus === 'failed' || (typeof invalid === 'number' && invalid > 0 && !record.model_zero)) return 'error';
  return { success: 'credited', 'zero credit': 'zero', unpaired: 'unpaired' }[record.outcome] || 'unresolved';
}

export function attemptOutcome(attempt) {
  if (!attempt) return 'missing';
  if (attempt.status === 'interrupted') return 'interrupted';
  if (!attempt.record) return attempt.recorded_status === 'running' ? 'running' : 'missing';
  return classify(attempt.record, attempt.status);
}

export function runnerOf(record) {
  if (!record) return 'unknown';
  if (record.reference || record.agent_bypassed || String(record.model || '').startsWith('reference/')) return 'reference';
  if (record.fixture || String(record.model || '').startsWith('fixture/')) return 'scripted';
  return record.runner || 'opencode';
}

export const RUNNER_LABELS = { claude: 'Claude Code', codex: 'Codex', cursor: 'Cursor', opencode: 'OpenCode', reference: 'Reference', scripted: 'Scripted', unknown: 'Unknown' };

export function count(n, singular, plural) {
  return `${formatNumber(n)} ${n === 1 ? singular : (plural || singular + 's')}`;
}

export function formatNumber(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return Number(n).toLocaleString('en-US');
}

export function compact(n) {
  if (n === null || n === undefined) return '—';
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + 'M';
  if (Math.abs(n) >= 1e4) return Math.round(n / 1e3) + 'k';
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(n);
}

export function duration(ms) {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s < 10 ? s.toFixed(1) : Math.round(s)} s`;
  const m = Math.floor(s / 60);
  const rest = Math.round(s - m * 60);
  if (m < 60) return `${m}m ${String(rest).padStart(2, '0')}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
}

export function seconds(s) { return s === null || s === undefined ? '—' : duration(s * 1000); }

export function clock(ms) {
  if (ms === null || ms === undefined) return '';
  const sign = ms < 0 ? '−' : '+';
  const total = Math.abs(ms) / 1000;
  const m = Math.floor(total / 60);
  const s = total - m * 60;
  return `${sign}${m}:${s.toFixed(1).padStart(4, '0')}`;
}

export function bytes(n) {
  if (n === null || n === undefined) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function when(epochSeconds) {
  if (!epochSeconds) return '—';
  const date = new Date(epochSeconds * 1000);
  return date.toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function ago(epochSeconds, now = Date.now() / 1000) {
  if (!epochSeconds) return '—';
  const d = Math.max(0, now - epochSeconds);
  if (d < 60) return 'just now';
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  if (d < 86400 * 30) return `${Math.floor(d / 86400)} d ago`;
  return when(epochSeconds);
}

export function shortHash(value, n = 10) { return value ? String(value).slice(0, n) : '—'; }

export function taskName(task) {
  const name = String(task || '').split('/').pop() || '';
  const acronyms = { tv: 'TV', ui: 'UI', url: 'URL', pdf: 'PDF', sms: 'SMS', api: 'API' };
  return name.replaceAll('_', '-').split('-').filter(Boolean)
    .map((w) => acronyms[w.toLowerCase()] || w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

export function platformOf(task) { return String(task || '').includes('/') ? String(task).split('/')[0] : 'unknown'; }

// ---------- tokenizers (return [type, text] pairs; DOM layer renders them) ----------
const PY_KEYWORDS = new Set(['False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await', 'break', 'class', 'continue',
  'def', 'del', 'elif', 'else', 'except', 'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda',
  'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield']);

export function tokenizePython(line) {
  const out = [];
  const re = /(#.*$)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\])*"?|'(?:\\.|[^'\\])*'?)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)(\s*\()?|(\s+)|(.)/g;
  let m;
  while ((m = re.exec(line)) !== null) {
    if (m[1]) out.push(['com', m[1]]);
    else if (m[2]) out.push(['str', m[2]]);
    else if (m[3]) out.push(['num', m[3]]);
    else if (m[4]) {
      if (PY_KEYWORDS.has(m[4])) out.push([['True', 'False', 'None'].includes(m[4]) ? 'lit' : 'kw', m[4]]);
      else if (m[5]) out.push(['fn', m[4]]);
      else out.push(['', m[4]]);
      if (m[5]) out.push(['', m[5]]);
    } else out.push(['', m[6] || m[7]]);
  }
  return out;
}

export function tokenizeJson(text) {
  const out = [];
  const re = /("(?:\\.|[^"\\])*")(\s*:)?|(-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|\b(true|false|null)\b|(\s+)|(.)/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m[1]) { out.push([m[2] ? 'key' : 'str', m[1]]); if (m[2]) out.push(['', m[2]]); }
    else if (m[3]) out.push(['num', m[3]]);
    else if (m[4]) out.push(['lit', m[4]]);
    else out.push(['', m[5] || m[6]]);
  }
  return out;
}

// Minimal, inert Markdown block parser. Returns a tree of plain objects.
export function parseMarkdown(text) {
  const lines = String(text || '').replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const lang = line.slice(3).trim();
      const body = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) body.push(lines[i++]);
      i++;
      blocks.push({ type: 'code', lang, text: body.join('\n') });
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) { blocks.push({ type: 'heading', level: heading[1].length, text: heading[2] }); i++; continue; }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) {
        let item = lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, '');
        i++;
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) item += ' ' + lines[i++].trim();
        items.push(item);
      }
      blocks.push({ type: ordered ? 'ol' : 'ul', items });
      continue;
    }
    if (!line.trim()) { i++; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^```/.test(lines[i]) && !/^#{1,4}\s/.test(lines[i]) && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) para.push(lines[i++]);
    blocks.push({ type: 'p', text: para.join('\n') });
  }
  return blocks;
}

export function parseInline(text) {
  const out = [];
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(['text', text.slice(last, m.index)]);
    if (m[1]) out.push(['code', m[1].slice(1, -1)]);
    else if (m[2]) out.push(['strong', m[2].slice(2, -2)]);
    else if (m[3]) out.push(['em', m[3].slice(1, -1)]);
    else if (m[4]) {
      const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(m[4]);
      out.push(['link', link[1], link[2]]);
    }
    last = re.lastIndex;
  }
  if (last < text.length) out.push(['text', text.slice(last)]);
  return out;
}

// Align two execution timelines by position; mark rows whose recorded status differs.
export function alignTimelines(left, right) {
  const significant = (rows) => (rows || []).filter((r) => r.kind !== 'record');
  const a = significant(left);
  const b = significant(right);
  const rows = [];
  let firstDivergence = null;
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const x = a[i] || null;
    const y = b[i] || null;
    const differs = !x || !y || x.status !== y.status || x.text !== y.text;
    if (differs && firstDivergence === null) firstDivergence = i;
    rows.push({ index: i + 1, left: x, right: y, differs });
  }
  return { rows, firstDivergence };
}

export function stepMatches(step, filter, query) {
  if (filter === 'actions' && step.kind !== 'tool') return false;
  if (filter === 'messages' && !['message', 'prompt'].includes(step.kind)) return false;
  if (filter === 'problems' && !['error', 'denied', 'blocked', 'incomplete'].includes(step.status)
      && !['interrupt', 'error', 'blocked'].includes(step.kind)) return false;
  if (filter === 'screens' && !(step.images || []).length) return false;
  if (!query) return true;
  const hay = [step.title, step.detail, step.text, step.tool, step.result && step.result.text,
    step.failure && step.failure.message, JSON.stringify(step.arguments || '')].join('\n').toLowerCase();
  return hay.includes(query.toLowerCase());
}
