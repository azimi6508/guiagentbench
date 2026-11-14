"""Run local reference, agent-boundary and execution controls without model inference."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    from gui_agent_bench.audit import audit_run
    from gui_agent_bench.fairness import task_binding, evidence_tree, runtime_binding, certificate_path, VERSION
    from gui_agent_bench.io import dump, digest
    from gui_agent_bench.run_plan import execute

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--task',
        action='append',
        dest='tasks',
        help='Qualify one task; repeat to select several. Default: discover all packages.',
    )
    parser.add_argument('--output', type=Path, default=None)
    parser.add_argument(
        '--install', action='store_true', help='Install a local certificate only after every control passes'
    )
    args = parser.parse_args()
    output = (args.output or ROOT / '.local/qualification' / uuid.uuid4().hex[:12]).resolve()
    output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'incomplete', 'model_inference': False, 'controls': [], 'automatic_retries': False}

    def save():
        dump(output / 'qualification.json', report)

    save()
    from gui_agent_bench.task_package import discover, task_path, metadata, verify

    identifiers = args.tasks or list(discover(ROOT))
    if not identifiers or len(set(identifiers)) != len(identifiers):
        parser.error('Select at least one unique task')
    tasks = []
    for identifier in identifiers:
        task = task_path(ROOT, identifier)
        verify(task)
        tasks.append({'task': identifier, 'arms': metadata(task)['metadata']['eligible_arms'], 'repeats': 1})
    before = {task: runtime_binding(ROOT, [task]) for task in identifiers}
    task_inputs = {task: task_binding(ROOT, task) for task in identifiers}
    try:
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT / 'src'))
        for name, command in [
            ('structure', [sys.executable, 'scripts/check_structure.py']),
            ('unit', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v']),
            ('viewer', ['node', 'tests/viewer_frontend.cjs']),
        ]:
            with (output / (name + '.log')).open('w') as log:
                result = subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
            report['controls'].append({'name': name, 'passed': result.returncode == 0})
            save()
            if result.returncode:
                raise RuntimeError(name + ' checks failed; evidence retained')
        for name, model, probes in [
            ('reference', 'reference/solution', False),
            ('scripted-probes', 'fixture/scripted', True),
        ]:
            plan = {'schema': 'run-plan-v1', 'name': name, 'models': [model], 'tasks': tasks}
            path, manifest = execute(ROOT, plan, output / name, allow_candidate=True, fixture_probe=probes)
            if manifest['status'] != 'complete':
                raise RuntimeError(name + ' did not complete all controls')
            for cell in manifest['cells']:
                attempts = cell['attempts']
                if len(attempts) != 1 or attempts[0]['status'] != 'complete':
                    raise RuntimeError('Missing or invalid first control attempt')
                if model == 'reference/solution' or cell['arm'].startswith(('oracle_', 'test_')):
                    if attempts[0].get('score') != 1:
                        raise RuntimeError('Known-solution pair did not earn credit')
                directory = path / attempts[0]['path']
                audit_run(directory, require_probes=probes)
            report['controls'].append({'name': name, 'passed': True, 'cells': len(manifest['cells'])})
            save()
        # Exercise a forbidden execution operation on each example's real broker.
        from gui_agent_bench.trial import run

        for task in tasks:
            denial_arm = 'test_ui' if 'test_ui' in task['arms'] else 'test_visual'
            summary = run(
                ROOT,
                task['task'],
                denial_arm,
                'pair',
                'fixture/scripted',
                output / 'execution-denials',
                180,
                'PASS',
                True,
                True,
                'forbidden',
            )
            directory = Path(summary['run_directory'])
            if summary.get('paired_score') != 0:
                raise RuntimeError('Forbidden generated code earned credit')
            audit_run(directory, require_probes=True)
            metrics = list(directory.glob('trials/*/logs/verifier/metrics.json'))
            causes = {
                i['cause'] for p in metrics for i in json.loads(p.read_text()).get('diagnostics', {}).get('issues', [])
            }
            if 'policy_violation' not in causes:
                raise RuntimeError('Forbidden operation lacks a recorded policy denial')
        report['controls'].append({'name': 'execution-denials', 'passed': True, 'cells': len(tasks)})
        if {task: runtime_binding(ROOT, [task]) for task in identifiers} != before or {
            task: task_binding(ROOT, task) for task in identifiers
        } != task_inputs:
            raise RuntimeError('Runtime changed during qualification')
        report['status'] = 'passed'
        save()
        if args.install:
            relative = output.relative_to(ROOT).as_posix()
            tree = evidence_tree(ROOT, output)
            for task in identifiers:
                certificate = {
                    'schema': VERSION,
                    'status': 'passed',
                    'task': task,
                    'runtime': before[task],
                    'task_sha256': task_inputs[task],
                    'evidence': {
                        relative + '/qualification.json': digest((output / 'qualification.json').read_bytes())
                    },
                    'evidence_trees': {relative: tree},
                }
                dump(certificate_path(ROOT, task), certificate)
        print(json.dumps({'status': 'passed', 'output': str(output), 'installed': args.install}, indent=2))
        return 0
    except BaseException:
        report['status'] = 'failed'
        save()
        raise


if __name__ == '__main__':
    raise SystemExit(main())
