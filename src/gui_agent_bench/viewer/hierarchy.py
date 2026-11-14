"""Run/task/arm projections over explicit manifests and historical fixed plans.

References resolve only to already indexed, allowlisted evaluations. Historical
absolute paths are identifiers, never authority to read outside the viewer root.
"""

import hashlib
from collections import defaultdict
from pathlib import PurePosixPath

from gui_agent_bench.arms import ARM_IDS
from .evidence import json_file, linked

# Recorded run states after which no attempt can still be running.
ENDED = {'complete', 'completed_with_errors', 'interrupted', 'preflight_failed'}


def key(path):
    return 'r-' + hashlib.sha256(path.encode()).hexdigest()[:20]


def reference(value, folder, rows, *, historical=False, root_prefix=''):
    if not isinstance(value, str) or not value:
        return None
    value = value.replace('\\', '/')
    if '..' in PurePosixPath(value).parts:
        return None
    if historical:
        # Portable historical records kept their original checkout prefix.
        suffix = value[len('runs/') :] if value.startswith('runs/') else value.split('/runs/', 1)[-1]
        if root_prefix and suffix.startswith(root_prefix + '/'):
            suffix = suffix[len(root_prefix) + 1 :]
        matches = [r for r in rows if r['path'] == suffix]
    else:
        if value.startswith('/') or ':' in value:
            return None
        target = '/'.join(p for p in (folder, value) if p and p != '.')
        matches = [r for r in rows if r['path'] == target or r['path'].startswith(target + '/')]
    return matches[0] if len(matches) == 1 else None


def totals(cells):
    first = [c['attempts'][0] if c['attempts'] else {} for c in cells]
    return {
        'planned': len(cells),
        'finished': sum(
            (a.get('record') or {}).get('status') not in {None, 'running', 'incomplete'} or a.get('status') == 'failed'
            for a in first
        ),
        'credited': sum(
            a.get('status') != 'failed' and (a.get('record') or {}).get('outcome') == 'success' for a in first
        ),
        'zero': sum(
            (a.get('record') or {}).get('outcome') == 'zero credit' or a.get('status') in {'failed', 'interrupted'}
            for a in first
        ),
        'missing': sum(not a.get('record') and a.get('status') != 'interrupted' for a in first),
        'attempts': sum(len(c['attempts']) for c in cells),
    }


def manifest(folder):
    native, error = json_file(folder, 'run.json')
    if (folder / 'run.json').exists():
        if error or native.get('schema') != 'run-v1':
            raise ValueError('Unsupported or unreadable run manifest')
        return native, False
    plan, error = json_file(folder, 'plan.json')
    report, _ = json_file(folder, 'report.json')
    if error:
        raise ValueError('Unreadable historical plan')
    planned = plan.get('cells')
    if planned is None and isinstance(plan.get('tasks'), list) and isinstance(plan.get('arms'), list):
        planned = [{'task': t['task'], 'arm': a} for t in plan['tasks'] for a in plan['arms']]
    if not isinstance(planned, list):
        raise ValueError('Unrecognized historical plan')
    if plan.get('planned_task_arm_pairs') != len(planned):
        raise ValueError('Historical denominator does not match its planned cells')
    actual = report.get('cells', [])
    native = {
        'name': folder.name,
        'scope': report.get('scope', 'Historical scripted qualification'),
        'cells': [],
        'model': plan.get('model', 'fixture/scripted'),
    }
    for c in planned:
        matches = [x for x in actual if (x.get('task'), x.get('arm')) == (c.get('task'), c.get('arm'))]
        attempts = []
        for item in matches:
            attempts.extend(item.get('attempts', [item]))
        native['cells'].append({**c, 'attempts': attempts})
    return native, True


def project(index, rows):
    runs, owned, warnings, ended = [], set(), [], []
    root_path = index.root.as_posix()
    root_prefix = root_path.split('/runs/', 1)[1] if '/runs/' in root_path else ''
    for folder in index.collections:
        relative = folder.relative_to(index.root).as_posix()
        try:
            if any(linked(p) for p in [folder, *folder.parents]):
                raise ValueError('Linked collection rejected')
            native, historical = manifest(folder)
        except (OSError, KeyError, TypeError, ValueError, AttributeError):
            warnings.append(f'{relative}: unreadable or unsupported run manifest')
            continue
        cells = []
        members = set()
        try:
            if not isinstance(native.get('cells'), list) or not native['cells']:
                raise ValueError('No planned cells')
            seen = set()
            for i, c in enumerate(native['cells']):
                if not isinstance(c.get('task'), str) or c.get('arm') not in ARM_IDS:
                    raise ValueError('Invalid task or arm')
                identity = (c['task'], c['arm'], c.get('model', native.get('model')), c.get('repeat', 1))
                if identity in seen:
                    raise ValueError('Duplicate planned cell')
                seen.add(identity)
                attempts = []
                for a in c.get('attempts', []):
                    target = a.get('run_directory', a.get('run')) if historical else a.get('path')
                    record = reference(
                        target,
                        relative,
                        rows,
                        historical=historical,
                        root_prefix=root_prefix or (folder.name if folder == index.root else ''),
                    )
                    mismatch = record and (
                        record['task'] != c['task']
                        or record['arm'] != c['arm']
                        or (identity[2] and record['model'] != identity[2])
                    )
                    if record and c.get('agent_spec') is not None:
                        mismatch = (
                            mismatch
                            or record.get('agent_spec') != c['agent_spec']
                            or record.get('configuration_sha256') != c.get('configuration_sha256')
                            or record.get('parent_resolved_plan_sha256') != native.get('resolved_plan_sha256')
                        )
                    if mismatch:
                        record = None
                    if record:
                        if record['id'] in members:
                            raise ValueError('Evaluation referenced more than once')
                        members.add(record['id'])
                    recorded_status = a.get('status', 'failed' if a.get('error') or a.get('reason') else 'recorded')
                    invalid = a.get('invalid_or_missing', (record or {}).get('invalid_or_missing'))
                    status = recorded_status
                    if recorded_status == 'running' and native.get('status') in ENDED:
                        status = 'interrupted'
                    elif record and record.get('model_zero') and recorded_status in {'failed', 'complete'}:
                        status = 'complete'
                    elif isinstance(invalid, (int, float)) and invalid > 0 and recorded_status != 'interrupted':
                        status = 'failed'
                    attempts.append(
                        {
                            'record': record,
                            'status': status,
                            'recorded_status': recorded_status,
                            'invalid_or_missing': invalid,
                            'error': a.get('error', a.get('reason')),
                            'qualified': a.get('qualified'),
                            'reference': target,
                            'unavailable': bool(target) and not record,
                        }
                    )
                cells.append(
                    {
                        'id': str(i),
                        'task': c['task'],
                        'arm': c['arm'],
                        'model': identity[2] or 'Unknown',
                        'repeat': c.get('repeat', 1),
                        'attempts': attempts,
                    }
                )
        except (KeyError, TypeError, ValueError, AttributeError):
            warnings.append(f'{relative}: invalid run manifest; individual evidence remains available')
            continue
        owned.update(members)
        runs.append(
            build(
                key(relative),
                native.get('name', folder.name),
                relative,
                cells,
                'historical' if historical else 'run',
                native.get('scope', ''),
                max(
                    [folder.stat().st_mtime]
                    + [a['record']['modified'] for c in cells for a in c['attempts'] if a['record']]
                ),
                native.get('status', 'recorded'),
            )
        )
        run = runs[-1]
        run['recorded_status'] = run['status']
        if run['status'] == 'complete' and any(a['status'] == 'failed' for c in cells for a in c['attempts']):
            run['status'] = 'completed_with_errors'
        run['preflight'] = native.get('preflight')
        run['stop_reason'] = native.get('stop_reason')
        if not historical:
            # A live run's unfinished evaluation is not yet linked to its plan; it is still that run's cell.
            ended.append(relative)
    for row in rows:
        # An unfinished evaluation inside a grouped run is shown through its run's cell.
        unfinished = row['status'] in {'running', 'incomplete'} and any(
            row['path'].startswith(path + '/') for path in ended
        )
        if row['id'] not in owned and not unfinished:
            runs.append(
                build(
                    key(row['path']),
                    row['name'],
                    row['path'],
                    [
                        {
                            'id': '0',
                            'task': row['task'],
                            'arm': row['arm'],
                            'model': row['model'],
                            'repeat': 1,
                            'attempts': [{'record': row, 'status': 'recorded', 'error': None}],
                        }
                    ],
                    'single',
                    'Individual historical evaluation',
                    row['modified'],
                    row['status'],
                )
            )
    return {
        'runs': sorted(runs, key=lambda r: (r['kind'] != 'single', r['modified']), reverse=True),
        'evaluations': rows,
        'warnings': warnings,
    }


def build(identifier, name, path, cells, kind, scope, modified, status):
    grouped = defaultdict(list)
    for c in cells:
        grouped[c['task']].append(c)
    tasks = [
        {'id': task, 'platform': task.split('/')[0] if '/' in task else 'unknown', 'cells': cs, 'totals': totals(cs)}
        for task, cs in grouped.items()
    ]
    return {
        'id': identifier,
        'name': name,
        'path': path,
        'kind': kind,
        'scope': scope,
        'status': status,
        'modified': modified,
        'tasks': tasks,
        'totals': totals(cells),
        'platforms': sorted({t['platform'] for t in tasks}),
        'models': sorted({c['model'] for c in cells}),
        'arms': [a for a in ARM_IDS if any(c['arm'] == a for c in cells)],
    }
