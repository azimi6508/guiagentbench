// Run with `node tests/viewer_frontend.cjs`. No browser or npm dependencies.
// format.js is an ES module without a package.json type marker, so it is imported from a temporary .mjs copy.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

(async () => {
  const source = path.join(__dirname, '../src/gui_agent_bench/viewer/static/js/format.js');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-format-'));
  const copy = path.join(dir, 'format.mjs');
  fs.copyFileSync(source, copy);
  const f = await import(pathToFileURL(copy).href);

  // Outcome buckets match the Python review model; missing evidence never becomes credit.
  assert.equal(f.classify(null), 'missing');
  assert.equal(f.classify({ status: 'running', outcome: 'success' }), 'running');
  assert.equal(f.classify({ status: 'complete', outcome: 'success', invalid_or_missing: 1 }), 'error');
  assert.equal(f.classify({ status: 'complete', outcome: 'success' }, 'failed'), 'error');
  assert.equal(f.classify({ status: 'complete', outcome: 'success' }), 'credited');
  assert.equal(f.classify({ status: 'complete', outcome: 'zero credit' }), 'zero');
  assert.equal(f.classify({ status: 'complete', outcome: 'unpaired' }), 'unpaired');
  assert.equal(f.attemptOutcome({ record: null, recorded_status: 'running' }), 'running');
  assert.equal(f.attemptOutcome({ record: null, recorded_status: 'failed' }), 'missing');
  assert.equal(f.classify({ status: 'complete', outcome: 'zero credit', invalid_or_missing: 1, model_zero: true }), 'zero');
  assert.equal(f.classify({ status: 'complete', outcome: 'zero credit', invalid_or_missing: 1, model_zero: true }, 'failed'), 'error');
  assert.equal(f.classify({ status: 'running', outcome: 'unresolved' }, 'interrupted'), 'interrupted');
  assert.equal(f.attemptOutcome({ record: null, recorded_status: 'running', status: 'interrupted' }), 'interrupted');
  assert.equal(f.runnerOf({ model: 'reference/solution' }), 'reference');
  assert.equal(f.runnerOf({ fixture: true, model: 'fixture/scripted' }), 'scripted');
  assert.equal(f.runnerOf({ runner: 'codex', model: 'codex/x' }), 'codex');

  // Formatting never invents values.
  assert.equal(f.duration(null), '—');
  assert.equal(f.duration(850), '850 ms');
  assert.equal(f.duration(39593), '40 s');
  assert.equal(f.duration(104000), '1m 44s');
  assert.equal(f.clock(-10), '−0:00.0');
  assert.equal(f.clock(19596), '+0:19.6');
  assert.equal(f.bytes(17368), '17 KB');
  assert.equal(f.compact(187000), '187k');
  assert.equal(f.taskName('tv/tv_sound_controls'), 'TV Sound Controls');
  assert.equal(f.causeText('missing_submission'), 'No submission was produced.');
  assert.equal(f.causeText('not_a_cause'), null);

  // Tokenizers keep every character; rendering is text-only.
  const line = 'page.expect_image("saved", region=[1, 2, 3, 4], precondition=True)  # check';
  assert.equal(f.tokenizePython(line).map(([, t]) => t).join(''), line);
  assert.ok(f.tokenizePython(line).some(([k, t]) => k === 'str' && t === '"saved"'));
  assert.ok(f.tokenizePython(line).some(([k, t]) => k === 'lit' && t === 'True'));
  assert.ok(f.tokenizePython(line).some(([k]) => k === 'com'));
  const json = '{"verdict": "PASS", "n": 3, "ok": true}';
  assert.equal(f.tokenizeJson(json).map(([, t]) => t).join(''), json);
  assert.ok(f.tokenizeJson(json).some(([k, t]) => k === 'key' && t === '"verdict"'));

  // Markdown is parsed to plain block/inline records; HTML stays literal text.
  const blocks = f.parseMarkdown('# Title\n\nUse `code` and **bold** <script>x</script>\n\n- one\n- two\n\n```\nraw <b>\n```');
  assert.deepEqual(blocks.map((b) => b.type), ['heading', 'p', 'ul', 'code']);
  assert.equal(blocks[3].text, 'raw <b>');
  const inline = f.parseInline(blocks[1].text);
  assert.deepEqual(inline.map(([k]) => k), ['text', 'code', 'text', 'strong', 'text']);
  assert.ok(inline[4][1].includes('<script>'));
  assert.deepEqual(f.parseInline('[test.py](/workspace/output/test.py)'), [['link', 'test.py', '/workspace/output/test.py']]);

  // Execution alignment reports the first divergence and keeps unequal lengths.
  const a = [{ kind: 'action', text: 'Click', status: 'ok' }, { kind: 'assertion', text: 'Saved', status: 'ok' }];
  const b = [{ kind: 'action', text: 'Click', status: 'ok' }, { kind: 'assertion', text: 'Saved', status: 'mismatch' }, { kind: 'failure', text: 'x', status: 'error' }];
  const aligned = f.alignTimelines(a, b);
  assert.equal(aligned.firstDivergence, 1);
  assert.equal(aligned.rows.length, 3);
  assert.equal(aligned.rows[2].left, null);

  // Trajectory filters.
  const tool = { kind: 'tool', status: 'denied', title: 'Read /private/x', images: [] };
  const shot = { kind: 'tool', status: 'ok', title: 'Take screenshot', images: [{ sha256: 'x' }] };
  const message = { kind: 'message', status: 'ok', text: 'Saved the submission' };
  assert.ok(f.stepMatches(tool, 'problems', ''));
  assert.ok(!f.stepMatches(shot, 'problems', ''));
  assert.ok(f.stepMatches(shot, 'screens', ''));
  assert.ok(f.stepMatches(message, 'messages', 'submission'));
  assert.ok(!f.stepMatches(message, 'actions', ''));
  assert.ok(f.stepMatches({ kind: 'interrupt', status: 'error', title: 'Harness interrupted the turn' }, 'problems', ''));

  fs.rmSync(dir, { recursive: true, force: true });
  console.log('viewer frontend checks passed');
})().catch((error) => { console.error(error); process.exit(1); });
