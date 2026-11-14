"""Reviewer-facing projections: verdicts, paired executions and run overviews.

Everything is derived from recorded files that the evidence index already
serves. Rewards, statuses and denominators are copied, never recomputed into
new credit. Plain-language explanations only restate recorded fields.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath
import re
import threading
import time

from gui_agent_bench.arms import ARM_IDS, artifact_name, generated
from .evidence import SAFE_ID, display_value, json_file, obj
from . import trajectory as trajectories

VERSION = 'review-v1'
TEXT_LIMIT = 2_000_000
TRACEBACK = re.compile(r'File "/artifact/(test|oracle)\.py", line (\d+)')
ARMS = {
    'judge_visual': {
        'label': 'Visual judge',
        'family': 'judge',
        'evidence': 'visual',
        'summary': 'Reads a recorded screenshot sequence and decides whether the GUI test run should PASS or FAIL.',
    },
    'judge_test': {
        'label': 'Test judge',
        'family': 'judge',
        'evidence': 'test',
        'summary': 'Reads the public test source, may interact with the live app, and decides PASS or FAIL.',
    },
    'oracle_visual': {
        'label': 'Visual oracle',
        'family': 'oracle',
        'evidence': 'visual',
        'summary': 'Follows the supplied journey steps and writes oracle.py with reference-image assertions.',
    },
    'oracle_ui': {
        'label': 'UI oracle',
        'family': 'oracle',
        'evidence': 'ui',
        'summary': 'Follows the supplied journey steps and writes oracle.py with UI-structure assertions.',
    },
    'test_visual': {
        'label': 'Visual test',
        'family': 'test',
        'evidence': 'visual',
        'summary': 'Writes a complete test.py from the goal alone, using reference-image assertions.',
    },
    'test_ui': {
        'label': 'UI test',
        'family': 'test',
        'evidence': 'ui',
        'summary': 'Writes a complete test.py from the goal alone, using UI-structure (and coordinate) actions and assertions.',
    },
}


def arm_info(arm):
    info = dict(ARMS.get(arm, {'label': str(arm), 'family': 'unknown', 'evidence': 'unknown', 'summary': ''}))
    info['id'] = arm
    info['generated'] = bool(arm) and generated(arm)
    info['artifact'] = artifact_name(arm) if arm in ARM_IDS else None
    return info


def issues_of(diagnostics):
    return [i for i in obj(diagnostics).get('issues') or [] if isinstance(i, dict)]


def first_zero_credit(issues):
    for impact in ('zero_credit', 'pair_dependent', None):
        for issue in issues:
            if impact is None or issue.get('impact') == impact:
                return issue
    return None


def classify(row, attempt_status=None):
    """Outcome bucket for one evaluation listing row.

    'error' needs review (framework, environment, provider or unclassified
    failure); invalid results explained entirely by the model are 'zero'.
    """
    if attempt_status == 'interrupted':
        return 'interrupted'
    if not row:
        return 'missing'
    status = row.get('status')
    if status == 'running' or (status == 'incomplete' and attempt_status in (None, 'running')):
        return 'running'
    if status == 'incomplete':
        return 'error'
    invalid = row.get('invalid_or_missing')
    if attempt_status == 'failed' or (isinstance(invalid, (int, float)) and invalid > 0 and not row.get('model_zero')):
        return 'error'
    return {'success': 'credited', 'zero credit': 'zero', 'unpaired': 'unpaired'}.get(row.get('outcome'), 'unresolved')


def assertion_text(assertion):
    assertion = obj(assertion)
    if assertion.get('kind') == 'image':
        region = assertion.get('region')
        where = f' in region {region}' if region else ''
        return f'Screen matches reference “{assertion.get("reference")}”{where}'
    query = obj(assertion.get('query'))
    target = (
        ' '.join(
            filter(
                None,
                [
                    query.get('role'),
                    f'“{query["name"]}”' if query.get('name') else None,
                    f'with text “{query["text"]}”' if query.get('text') else None,
                ],
            )
        )
        or 'element'
    )
    condition = assertion.get('condition', 'matches')
    expected = assertion.get('expected', True)
    if condition == 'visible':
        return f'{target} is {"visible" if expected else "not visible"}'
    if 'value' in assertion:
        return f'{target} has value “{assertion.get("value")}”'
    return f'{target} {condition.replace("_", " ")}{"" if expected else " (negated)"}'


def action_text(action):
    action = obj(action)
    operation = action.get('operation')
    args = obj(action.get('arguments'))
    if operation == 'step':
        return trajectories.describe_step(args)[0]
    if operation == 'open_url':
        return f'Open {args.get("url", "URL")}'
    if operation == 'reset':
        return 'Reset app'
    return str(operation or 'action').replace('_', ' ').capitalize()


def execution_timeline(index, run_id, path):
    """Rows from an execution browser.log: actions, assertions, failures, in source order."""
    rows = []
    try:
        records = list(index.records(run_id, path))
    except (FileNotFoundError, ValueError):
        return rows
    for line, _, event, error in records:
        record_index = line - 1
        if error:
            rows.append(
                {'kind': 'notice', 'line': line, 'record_index': record_index, 'text': error, 'status': 'warning'}
            )
        elif 'environment_event' in event:
            rows.append(
                {
                    'kind': 'environment',
                    'line': line,
                    'record_index': record_index,
                    'text': f'Environment {event.get("environment_event")}: {event.get("status")}',
                    'status': 'ok' if event.get('status') == 'ready' else 'error',
                }
            )
        elif 'setup' in event:
            rows.append(
                {
                    'kind': 'environment',
                    'line': line,
                    'record_index': record_index,
                    'text': f'Setup {event.get("setup")}' + (' (initial state)' if event.get('initial_state') else ''),
                    'status': 'ok' if event.get('setup') == 'ready' else 'error',
                }
            )
        elif 'action' in event:
            rows.append(
                {
                    'kind': 'action',
                    'line': line,
                    'record_index': record_index,
                    'text': action_text(event['action']),
                    'detail': display_value(event['action']),
                    'status': 'ok',
                }
            )
        elif 'assertion' in event:
            assertion = obj(event['assertion'])
            image = obj(event.get('image'))
            row = {
                'kind': 'assertion',
                'line': line,
                'record_index': record_index,
                'text': assertion_text(assertion),
                'assertion': display_value(assertion),
                'matched': event.get('matched'),
                'precondition': bool(assertion.get('precondition')),
                'status': 'ok' if event.get('matched') else 'mismatch',
            }
            if image:
                row['image'] = {
                    'different_pixels': image.get('different_pixels'),
                    'compared_pixels': image.get('compared_pixels'),
                    'directory': obj(image.get('evidence')).get('directory'),
                    'comparator': image.get('comparator'),
                }
            rows.append(row)
        elif event.get('operation_failed') or event.get('failure'):
            failure = obj(event.get('failure'))
            rows.append(
                {
                    'kind': 'failure',
                    'line': line,
                    'record_index': record_index,
                    'text': failure.get('message') or 'Operation failed',
                    'cause': failure.get('cause'),
                    'underlying': failure.get('underlying_causes'),
                    'denied': event.get('denied'),
                    'status': 'error',
                }
            )
        elif 'operation' in event and rows:
            previous = rows[-1]
            previous.setdefault('acks', []).append(line)
            if event.get('denied'):
                previous['status'] = 'denied'
        else:
            rows.append(
                {
                    'kind': 'record',
                    'line': line,
                    'record_index': record_index,
                    'text': json.dumps(display_value(event))[:300],
                    'status': 'info',
                }
            )
    return rows


def read_text(index, run_id, relative):
    try:
        path = index.artifact(run_id, relative)
        size = path.stat().st_size
        with path.open('rb') as source:
            data = source.read(TEXT_LIMIT)
        return {
            'path': relative,
            'size': size,
            'text': data.decode('utf-8', errors='replace'),
            'complete': size <= TEXT_LIMIT,
        }
    except (FileNotFoundError, ValueError, OSError):
        return None


def verdict(plan, trials):
    """Plain-language verdict built only from recorded metrics."""
    arm = plan.get('arm')
    info = arm_info(arm)
    lines = []
    if info['family'] == 'judge':
        for trial in trials:
            m = trial['metrics']
            role = 'correct' if trial.get('variant') == 'correct' else 'faulty'
            if m.get('status') == 'graded':
                ok = m.get('prediction') == m.get('expected')
                lines.append(
                    {
                        'tone': 'good' if ok else 'bad',
                        'trial': trial['id'],
                        'text': f'{role.capitalize()}-state recording: judged {m.get("prediction")}, expected {m.get("expected")}.',
                    }
                )
            elif m:
                issue = first_zero_credit(issues_of(m.get('diagnostics')))
                lines.append(
                    {
                        'tone': 'bad',
                        'trial': trial['id'],
                        'text': f'{role.capitalize()}-state recording: {m.get("reason") or (issue or {}).get("message") or m.get("status")}',
                        'cause': (issue or {}).get('cause'),
                    }
                )
            else:
                lines.append(
                    {
                        'tone': 'muted',
                        'trial': trial['id'],
                        'text': f'{role.capitalize()}-state recording: no result recorded.',
                    }
                )
        return lines
    for trial in trials:
        m = trial['metrics']
        executions = trial.get('executions') or []
        if not m:
            lines.append({'tone': 'muted', 'text': 'No grading result has been recorded yet.'})
            continue
        if m.get('status') in {'trial_error', 'invalid_submission'}:
            issue = first_zero_credit(issues_of(m.get('diagnostics')))
            phase = 'Authoring' if m.get('status') == 'trial_error' else 'Submission'
            lines.append(
                {
                    'tone': 'bad',
                    'text': f'{phase} failed: {m.get("reason") or (issue or {}).get("message")}',
                    'cause': (issue or {}).get('cause'),
                }
            )
            continue
        outcomes = {e['variant']: e for e in executions}
        for variant in ('correct', 'faulty'):
            e = outcomes.get(variant)
            if not e:
                lines.append({'tone': 'muted', 'text': f'{variant.capitalize()} app: no execution recorded.'})
                continue
            outcome = obj(e['result']).get('outcome')
            assertions = obj(e['result']).get('assertions') or []
            matched = sum(bool(a.get('matched')) for a in assertions if isinstance(a, dict))
            first_miss = next(
                (i for i, a in enumerate(assertions, 1) if isinstance(a, dict) and not a.get('matched')), None
            )
            expected_outcome = 'PASS' if variant == 'correct' else 'BEHAVIOR_FAIL'
            tone = 'good' if outcome == expected_outcome else 'bad'
            text = f'{variant.capitalize()} app: {outcome or "no outcome"}'
            if assertions:
                text += f' — {matched}/{len(assertions)} assertions matched'
            if first_miss is not None:
                text += f', first mismatch at assertion #{first_miss}'
            issue = first_zero_credit(issues_of(obj(e['result']).get('diagnostics')))
            if outcome in {'ERROR', 'SETUP_ERROR'} and issue:
                text += f' — {str(issue.get("message", "")).rstrip(".")}'
            lines.append({'tone': tone, 'text': text + '.', 'execution': e['id'], 'cause': (issue or {}).get('cause')})
        correct = obj(obj(outcomes.get('correct')).get('result')).get('outcome')
        faulty = obj(obj(outcomes.get('faulty')).get('result')).get('outcome')
        if correct == 'PASS' and faulty == 'PASS':
            lines.append(
                {'tone': 'bad', 'text': 'The program passed on the faulty app, so the fault was not detected.'}
            )
        elif correct == 'BEHAVIOR_FAIL':
            lines.append(
                {'tone': 'bad', 'text': 'The program failed on the correct app, so it cannot distinguish the fault.'}
            )
        elif correct == 'PASS' and faulty == 'BEHAVIOR_FAIL' and m.get('reward') == 1:
            lines.append({'tone': 'good', 'text': 'The program passed on the correct app and detected the fault.'})
        if {correct, faulty} & {'ERROR', 'SETUP_ERROR'}:
            lines.append(
                {
                    'tone': 'muted',
                    'text': 'Execution errors and failed preconditions earn zero credit; '
                    'they never count as fault detection.',
                }
            )
    return lines


def short_reason(plan, trials, outcome):
    """One-line cause for overview cells. Only restates recorded fields."""
    family = arm_info(plan.get('arm'))['family']
    if outcome == 'credited':
        return 'Credited'
    if outcome == 'running':
        return 'Running'
    if outcome == 'interrupted':
        return 'Interrupted before grading'
    if outcome == 'missing':
        return 'Not recorded'
    for trial in trials:
        m = trial.get('metrics') or {}
        variant = trial.get('variant')
        if family == 'judge':
            if m.get('status') == 'graded' and m.get('prediction') != m.get('expected'):
                return f'Wrong verdict on {variant} state'
            if m and m.get('status') != 'graded':
                issue = first_zero_credit(issues_of(m.get('diagnostics')))
                return f'{human((issue or {}).get("cause") or m.get("status"))} ({variant} state)'
            continue
        if m.get('status') in {'trial_error', 'invalid_submission'}:
            issue = first_zero_credit(issues_of(m.get('diagnostics')))
            return human((issue or {}).get('cause') or m.get('status'))
        executions = [e for e in m.get('executions') or [] if isinstance(e, dict)]
        if executions:
            # Older two-execution records carry no variant; they are ordered correct, faulty.
            variants = [e.get('variant') or ('correct', 'faulty')[i % 2] for i, e in enumerate(executions)]
            correct = {e.get('outcome') for e, v in zip(executions, variants) if v == 'correct'}
            faulty = {e.get('outcome') for e, v in zip(executions, variants) if v == 'faulty'}
            if (correct | faulty) & {'ERROR', 'SETUP_ERROR'}:
                issue = first_zero_credit(issues_of(m.get('diagnostics')))
                return human((issue or {}).get('cause') or 'execution error')
            if len(correct) > 1 or len(faulty) > 1:
                return 'Unstable across repeated executions'
            if correct == {'PASS'} and faulty == {'PASS'}:
                return 'Fault not detected'
            if correct == {'BEHAVIOR_FAIL'}:
                return 'Failed on correct app'
    return {'unresolved': 'Result not recorded', 'unpaired': 'Single-state judgment', 'error': 'Needs review'}.get(
        outcome, 'Zero credit'
    )


def total_tokens(usage):
    """Recorded total, or input + output + cache tokens for runners that report no total."""
    if isinstance(usage.get('totalTokens'), (int, float)):
        return usage['totalTokens']
    parts = [usage.get(k) for k in ('inputTokens', 'outputTokens', 'cacheCreationInputTokens', 'cacheReadInputTokens')]
    known = [p for p in parts if isinstance(p, (int, float))]
    return sum(known) if known else None


def human(value):
    return str(value or 'unknown').replace('_', ' ').capitalize()


def find_audit(index, run_id):
    """Recorded boundary audit results that reference this evaluation, if any."""
    key = index.runs.get(run_id, (None, ''))[1]
    if not key:
        return None
    parts = PurePosixPath(key).parts
    for depth in range(len(parts) - 1, -1, -1):
        folder = index.root.joinpath(*parts[:depth])
        candidate = folder / 'audits.json'
        if not candidate.is_file() or candidate.is_symlink():
            continue
        data, error = json_file(folder, 'audits.json')
        if error:
            continue
        for result in data.get('results') or []:
            target = str(obj(result).get('evaluation', '')).replace('\\', '/')
            if target and (target == key or target.endswith('/' + key) or key.endswith('/' + target)):
                stdout = result.get('stdout')
                try:
                    report = json.loads(stdout) if isinstance(stdout, str) else {}
                except ValueError:
                    report = {}
                return {
                    'file': PurePosixPath(*parts[:depth], 'audits.json').as_posix(),
                    'schema': data.get('schema'),
                    'returncode': result.get('returncode'),
                    'status': obj(report).get('status'),
                    'scope': obj(report).get('scope'),
                    'reason': obj(report).get('reason'),
                    'runtime_verified': obj(report).get('runtime_verified'),
                    'trials': [
                        {
                            k: v
                            for k, v in obj(t).items()
                            if k
                            in {
                                'trial_id',
                                'status',
                                'bridge_calls',
                                'denied_probes',
                                'images_agent_chose_to_read',
                                'authoring_recoveries',
                                'runner',
                            }
                        }
                        for t in obj(report).get('trials') or []
                    ],
                }
    return None


class Reviewer:
    def __init__(self, index):
        self.index = index
        self.lock = threading.RLock()
        self.cache = {}
        self.rows, self.rows_at = {}, 0.0

    def row(self, run_id):
        """Listing record for one evaluation; listings are reused for two seconds."""
        with self.lock:
            if run_id not in self.rows or time.monotonic() - self.rows_at > 2:
                self.rows = {r['id']: r for r in self.index.listing()['runs']}
                self.rows_at = time.monotonic()
            return self.rows.get(run_id)

    def provisional(self, run, cell, attempt):
        """Link a live attempt whose run lineage the controller has not attested yet.

        The pinned hierarchy only links attested evaluations. While an attempt is
        recorded as running, its plan lacks the parent plan hash; everything else
        must already match the run manifest. Finished evaluations are never linked here.
        """
        reference = attempt.get('reference')
        if (
            attempt.get('recorded_status') not in {'running', 'interrupted'}
            or not isinstance(reference, str)
            or '..' in reference
            or reference.startswith('/')
            or ':' in reference
        ):
            return None
        manifest, error = json_file(self.index.root / run['path'], 'run.json') if run['kind'] == 'run' else ({}, 'n/a')
        cells = manifest.get('cells') if not error else None
        if not isinstance(cells, list) or not cell['id'].isdigit() or int(cell['id']) >= len(cells):
            return None
        planned = obj(cells[int(cell['id'])])
        target = f"{run['path']}/{reference}".strip('/')
        matches = [r for r in self.index.listing()['runs'] if r['path'] == target or r['path'].startswith(target + '/')]
        if len(matches) != 1:
            return None
        record = matches[0]
        if (
            (record['task'], record['arm']) != (cell['task'], cell['arm'])
            or record['model'] != cell['model']
            or record.get('status') not in {'running', 'incomplete'}
            or record.get('parent_resolved_plan_sha256') is not None
            or record.get('agent_spec') != planned.get('agent_spec')
            or record.get('configuration_sha256') != planned.get('configuration_sha256')
        ):
            return None
        return record

    def trajectory(self, run_id, trial_id, detail_paths=None):
        if trial_id != 'external' and not SAFE_ID.fullmatch(trial_id or ''):
            raise ValueError('Invalid trial')
        prefix = '' if trial_id == 'external' else f'trials/{trial_id}/'
        detail_paths = detail_paths or self.paths(run_id)
        signature = tuple(sorted((p, s, m) for p, s, m in detail_paths['signature'] if p.startswith(prefix + 'logs/')))
        key = (run_id, prefix)
        with self.lock:
            cached = self.cache.get(key)
            if cached and cached[0] == signature:
                return cached[1]
        value = trajectories.build(self.index, run_id, prefix, detail_paths['paths'])
        with self.lock:
            self.cache[key] = (signature, value)
            if len(self.cache) > 96:
                self.cache.pop(next(iter(self.cache)))
        return value

    def paths(self, run_id):
        from .evidence import allowed, walk

        root = self.index.directory(run_id)
        paths, signature = set(), []
        for path in walk(root):
            relative = path.relative_to(root).as_posix()
            if allowed(relative):
                info = path.stat()
                paths.add(relative)
                signature.append((relative, info.st_size, info.st_mtime_ns))
        return {'paths': paths, 'signature': signature}

    def evaluation(self, run_id):
        index = self.index
        detail = index.detail(run_id)
        plan, summary = detail['plan'], detail['summary']
        paths = {a['path'] for a in detail['artifacts']}
        arm = arm_info(plan.get('arm'))
        path_info = self.paths(run_id)
        trials = []
        for trial in detail['trials']:
            prefix = trial['prefix']
            metrics = trial['metrics'] or {}
            judgment = None
            if trial.get('sealed_file') and trial['sealed_file'].endswith('judgment.json'):
                judgment, _ = json_file(index.directory(run_id), trial['sealed_file'])
            agent_summary = {}
            if prefix + 'logs/agent/summary.json' in paths:
                agent_summary, _ = json_file(index.directory(run_id), prefix + 'logs/agent/summary.json')
            agent_plan = {}
            if prefix + 'agent-plan.json' in paths:
                agent_plan, _ = json_file(index.directory(run_id), prefix + 'agent-plan.json')
            isolation = {}
            if prefix + 'isolation.json' in paths:
                isolation, _ = json_file(index.directory(run_id), prefix + 'isolation.json')
            try:
                traj = self.trajectory(run_id, trial['id'], path_info)
            except (OSError, ValueError):
                traj = None
            executions = []
            for e in trial['executions']:
                base = e['path'].rsplit('/', 1)[0] + '/'
                result = obj(e['result'])
                timeline = (
                    execution_timeline(index, run_id, base + 'browser.log') if base + 'browser.log' in paths else []
                )
                stderr = read_text(index, run_id, base + 'stderr.log') if base + 'stderr.log' in paths else None
                lines = sorted({int(n) for _, n in TRACEBACK.findall((stderr or {}).get('text') or '')})
                images = []
                for image in e['images']:
                    directory = image['directory']
                    files = {
                        name: directory + '/' + name
                        for name in ('expected.png', 'actual.png', 'diff.png', 'capture.png')
                        if directory + '/' + name in paths
                    }
                    images.append(
                        {
                            'directory': directory.rsplit('/', 1)[-1],
                            'path': directory,
                            'files': files,
                            'result': display_value(image['result']),
                        }
                    )
                executions.append(
                    {
                        'id': e['id'],
                        'variant': e['variant'],
                        'outcome': result.get('outcome'),
                        'elapsed_seconds': result.get('elapsed_seconds'),
                        'exit_code': result.get('exit_code'),
                        'assertions': display_value(result.get('assertions') or []),
                        'actions': len(result.get('actions') or []),
                        'issues': issues_of(result.get('diagnostics')),
                        'timeline': timeline,
                        'images': images,
                        'stderr': stderr,
                        'traceback_lines': lines,
                        'files': {
                            name: base + name
                            for name in (
                                'result.json',
                                'browser.log',
                                'stdout.log',
                                'stderr.log',
                                'termination.json',
                                'isolation.json',
                            )
                            if base + name in paths
                        },
                        'result': e['result'],
                    }
                )
            stats = traj['stats'] if traj else None
            trials.append(
                {
                    'id': trial['id'],
                    'variant': trial['variant'],
                    'prefix': prefix,
                    'missing': trial['missing'],
                    'metrics': display_value(metrics),
                    'metrics_path': trial['metrics_path'],
                    'judgment': display_value(judgment) if judgment else None,
                    'issues': issues_of(metrics.get('diagnostics')),
                    'agent': {
                        'elapsed_seconds': agent_summary.get('elapsed_seconds'),
                        'completed': agent_summary.get('completed'),
                        'shutdown_reason': agent_summary.get('shutdown_reason'),
                        'usage': agent_summary.get('usage'),
                        'issues': issues_of(agent_summary.get('diagnostics')),
                        'billing_mode': agent_summary.get('billing_mode'),
                        'opencode_version': agent_summary.get('opencode_version'),
                        'automatic_trial_retries': agent_summary.get('automatic_trial_retries'),
                        'budgets': agent_plan.get('budgets'),
                    },
                    'isolation': (
                        {'status': isolation.get('status'), 'schema': isolation.get('schema')} if isolation else None
                    ),
                    'trajectory': {
                        'available': traj is not None,
                        'runner': traj['runner'] if traj else None,
                        'stats': stats,
                        'end': traj['end'] if traj else None,
                        'warnings': traj['warnings'] if traj else [],
                    },
                    'executions': executions,
                    'pair_plan': display_value(trial['pair_plan']),
                    'submission': trial['submission'],
                    'sealed_file': trial['sealed_file'],
                    'sealed_hash_matches': trial['sealed_hash_matches'],
                    'sealed_text': read_text(index, run_id, trial['sealed_file']) if trial.get('sealed_file') else None,
                    'draft_files': trial['draft_files'],
                    'references': trial['references'],
                    'inputs': trial['inputs'],
                    'resources': trial['resources'],
                }
            )
        row = self.row(run_id) or {}
        outcome = classify(row)
        lines = verdict(
            plan,
            [
                {
                    **t,
                    'metrics': t['metrics'],
                    'executions': [
                        {'id': e['id'], 'variant': e['variant'], 'result': e['result']} for e in t['executions']
                    ],
                }
                for t in trials
            ],
        )
        if outcome == 'running':
            lines = [
                {
                    'tone': 'muted',
                    'text': (
                        'No readable summary is recorded for this evaluation: it is still running, or it '
                        'ended before one was written. Rewards appear once grading is recorded.'
                        if row.get('status') == 'incomplete'
                        else 'The evaluation is recorded as running; rewards appear once grading is '
                        'recorded. A running status alone does not prove the process is alive.'
                    ),
                }
            ]
        for t in trials:
            for e in t['executions']:
                e.pop('result', None)
        first = trials[0] if trials else {}
        instruction = read_text(index, run_id, first.get('prefix', '') + 'workspace/instruction.md') if first else None
        steps = None
        if first and first.get('prefix', '') + 'workspace/steps.json' in paths:
            try:
                steps = json.loads(
                    index.artifact(run_id, first['prefix'] + 'workspace/steps.json').read_text(encoding='utf-8')
                )
            except (ValueError, OSError):
                steps = None
        test_source = (
            read_text(index, run_id, first.get('prefix', '') + 'workspace/test_source.py')
            if first and first.get('prefix', '') + 'workspace/test_source.py' in paths
            else None
        )
        audit = find_audit(index, run_id)
        return {
            'version': VERSION,
            'id': run_id,
            'name': detail['name'],
            'path': index.runs[run_id][1],
            'task': plan.get('task'),
            'platform': plan.get('domain') or str(plan.get('task', '')).split('/')[0],
            'execution_platform': plan.get('platform'),
            'arm': arm,
            'model': plan.get('model'),
            'runner': (
                'reference' if plan.get('reference') or plan.get('agent_bypassed') else plan.get('runner', 'opencode')
            ),
            'kind': (
                'reference'
                if plan.get('reference') or plan.get('agent_bypassed')
                else 'fixture' if plan.get('fixture') else 'model'
            ),
            'outcome': outcome,
            'row': row,
            'summary': display_value(summary),
            'plan': display_value(plan),
            'verdict': lines,
            'reason': short_reason(plan, [{'variant': t['variant'], 'metrics': t['metrics']} for t in trials], outcome),
            'trials': trials,
            'instruction': instruction,
            'steps': steps,
            'test_source': test_source,
            'audit': audit,
            'integrity': integrity(trials, audit, summary),
            'warnings': detail['warnings'],
            'cost': detail['cost'],
            'last_evidence': detail['last_evidence'],
            'artifacts': detail['artifacts'],
        }

    def run_overview(self, key):
        hierarchy = self.index.hierarchy()
        run = next((r for r in hierarchy['runs'] if r['id'] == key), None)
        if run is None:
            raise FileNotFoundError('Run not found')
        cells, causes = [], {}
        for task in run['tasks']:
            for cell in task['cells']:
                first = cell['attempts'][0] if cell['attempts'] else {}
                record = first.get('record')
                lineage = None
                if not record and first:
                    record = self.provisional(run, cell, first)
                    lineage = ('unattested' if first.get('status') == 'interrupted' else 'pending') if record else None
                if record:
                    outcome = classify(record, first.get('status'))
                    facts = self.facts(record['id'], outcome)
                else:
                    outcome = (
                        'interrupted'
                        if first.get('status') == 'interrupted'
                        else 'running' if first.get('recorded_status') == 'running' else 'missing'
                    )
                    facts = {
                        'reason': (
                            'Not started'
                            if not first
                            else (
                                'Interrupted before grading; no evidence linked'
                                if outcome == 'interrupted'
                                else (
                                    'Recorded as running; no evidence linked yet'
                                    if outcome == 'running'
                                    else (
                                        'Evidence unavailable or does not match the plan'
                                        if first.get('unavailable')
                                        else human(first.get('status') or 'not recorded')
                                    )
                                )
                            )
                        )
                    }
                for cause, count in facts.get('causes', {}).items():
                    if outcome not in {'credited'}:
                        causes[cause] = causes.get(cause, 0) + 1
                cells.append(
                    {
                        'task': cell['task'],
                        'arm': cell['arm'],
                        'model': cell['model'],
                        'repeat': cell['repeat'],
                        'evaluation': record['id'] if record else None,
                        'outcome': outcome,
                        'attempts': len(cell['attempts']),
                        'error': first.get('error'),
                        'lineage': lineage,
                        'score': (record or {}).get('score'),
                        'status': (record or {}).get('status'),
                        'runner': (record or {}).get('runner'),
                        **facts,
                    }
                )
        return {'version': VERSION, 'run': run, 'cells': cells, 'causes': causes, 'warnings': hierarchy['warnings']}

    def facts(self, run_id, outcome):
        """Cheap per-evaluation facts for overview tables."""
        try:
            root = self.index.directory(run_id)
        except (FileNotFoundError, ValueError):
            return {}
        plan, _ = json_file(root, 'plan.json')
        summary, _ = json_file(root, 'summary.json')
        trials, seconds, tokens, tools = [], 0.0, 0, 0
        known_seconds = known_tokens = known_tools = False
        for cell in plan.get('trials') or []:
            trial = cell.get('id', '')
            if not SAFE_ID.fullmatch(trial):
                continue
            metrics, _ = json_file(root, f'trials/{trial}/logs/verifier/metrics.json')
            agent, _ = json_file(root, f'trials/{trial}/logs/agent/summary.json')
            trials.append({'variant': cell.get('variant'), 'metrics': metrics})
            if isinstance(agent.get('elapsed_seconds'), (int, float)):
                seconds += agent['elapsed_seconds']
                known_seconds = True
            total = total_tokens(obj(agent.get('usage')))
            if total is not None:
                tokens += total
                known_tokens = True
            if isinstance(agent.get('observed_tool_items'), int):
                tools += agent['observed_tool_items']
                known_tools = True
            elif (root / f'trials/{trial}/logs/agent/trajectory.ndjson').is_file():
                try:
                    traj = self.trajectory(run_id, trial)
                except (FileNotFoundError, ValueError, OSError):
                    traj = None
                if traj:
                    tools += traj['stats']['tool_calls']
                    known_tools = True
                    used = traj['stats'].get('tokens') or {}
                    if isinstance(used.get('input'), (int, float)):
                        tokens += used.get('input', 0) + used.get('output', 0)
                        known_tokens = True
        failure = obj(summary.get('failure_summary'))
        return {
            'causes': obj(failure.get('units_by_cause')),
            'reason': short_reason(plan, trials, outcome),
            'authoring_seconds': seconds if known_seconds else None,
            'tokens': tokens if known_tokens else None,
            'tool_calls': tools if known_tools else None,
            'kind': (
                'reference'
                if plan.get('reference') or plan.get('agent_bypassed')
                else 'fixture' if plan.get('fixture') else 'model'
            ),
        }


def integrity(trials, audit, summary):
    checks = []
    for t in trials:
        label = f'{str(t["variant"]).capitalize()}-state trial' if len(trials) > 1 else 'Trial'
        if t.get('sealed_file'):
            checks.append(
                {
                    'label': f'{label}: sealed submission hash matches its record',
                    'status': (
                        'pass'
                        if t['sealed_hash_matches']
                        else 'fail' if t['sealed_hash_matches'] is False else 'unknown'
                    ),
                }
            )
        refs = t.get('references') or []
        if refs:
            good = sum(r.get('hash_matches') is True for r in refs)
            checks.append(
                {
                    'label': f'{label}: sealed reference images match the manifest',
                    'status': 'pass' if good == len(refs) else 'fail',
                    'detail': f'{good}/{len(refs)}',
                }
            )
        inputs = [i for i in t.get('inputs') or [] if i.get('hash_matches') is not None]
        if inputs:
            good = sum(i['hash_matches'] for i in inputs)
            checks.append(
                {
                    'label': f'{label}: workspace inputs match the materialized manifest',
                    'status': 'pass' if good == len(inputs) else 'fail',
                    'detail': f'{good}/{len(inputs)}',
                }
            )
        if t.get('isolation'):
            checks.append(
                {
                    'label': f'{label}: isolation record',
                    'status': 'pass' if t['isolation'].get('status') == 'pass' else 'unknown',
                    'detail': t['isolation'].get('status'),
                }
            )
        retries = t['agent'].get('automatic_trial_retries')
        if retries is not None:
            checks.append(
                {'label': f'{label}: no automatic trial retries', 'status': 'pass' if retries is False else 'fail'}
            )
    if any(t['executions'] for t in trials):
        same = next((t['metrics'].get('same_assertions') for t in trials if 'same_assertions' in t['metrics']), None)
        if same is not None:
            checks.append(
                {
                    'label': 'Both executions recorded the same assertion definitions',
                    'status': 'pass' if same else 'warn',
                    'detail': (
                        None
                        if same
                        else 'The two executions recorded different assertion sequences; compare them in Execution.'
                    ),
                }
            )
    if audit:
        checks.append(
            {
                'label': 'Recorded boundary audit',
                'status': 'pass' if audit.get('status') == 'pass' else 'fail',
                'detail': ' · '.join(filter(None, [audit.get('scope'), audit.get('reason'), audit.get('file')])),
            }
        )
    else:
        checks.append(
            {
                'label': 'Recorded boundary audit',
                'status': 'unknown',
                'detail': 'No audits.json references this evaluation',
            }
        )
    if obj(summary.get('failure_summary')).get('automatic_retries') is False:
        checks.append({'label': 'Run summary: no automatic retries', 'status': 'pass'})
    return checks
