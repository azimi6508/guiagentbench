"""Validate source structure, arm policies, task registration and immutable source inputs."""

import ast
import json
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from gui_agent_bench.arms import ARM_IDS


def check(root=ROOT):
    errors = []
    required = [
        'README.md',
        'LICENSE',
        'NOTICE',
        'THIRD_PARTY_NOTICES.md',
        'AGENTS.md',
        'pyproject.toml',
        'docs/setup.md',
        'docs/running.md',
        'docs/architecture.md',
        'docs/task-authoring.md',
        'scripts/check_leakage.py',
        'jobs/examples-reference.json',
    ]
    for name in required:
        if not (root / name).is_file():
            errors.append('Missing file: ' + name)
    for base in ('src', 'scripts', 'tests'):
        for path in (root / base).rglob('*.py'):
            try:
                tree = ast.parse(path.read_text(), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('gui_agent_bench.'):
                        relative = node.module.split('.')[1:]
                        target = root / 'src/gui_agent_bench'
                        target = target.joinpath(*relative)
                        if not target.with_suffix('.py').is_file() and not (target / '__init__.py').is_file():
                            errors.append(
                                'Missing internal import in ' + path.relative_to(root).as_posix() + ': ' + node.module
                            )
            except (SyntaxError, UnicodeError) as exc:
                errors.append(str(exc))
    for arm in ARM_IDS:
        try:
            policy = tomllib.loads((root / 'configs/arms' / (arm + '.toml')).read_text())
            profile = json.loads((root / 'configs/opencode' / (arm + '.json')).read_text())
            if policy['arm'] != arm or policy['default'] != 'deny' or profile['permission']['*'] != 'deny':
                errors.append('Arm default-deny policy differs: ' + arm)
            if policy['files']['write'] != ['/workspace/output/*'] or policy['tools']['execute_submission']:
                errors.append('Arm output/execution boundary differs: ' + arm)
            expected_ui = arm in {'judge_test', 'oracle_ui', 'test_ui'}
            if policy['evidence']['ui_structure'] != expected_ui:
                errors.append('Arm UI evidence differs: ' + arm)
        except (OSError, KeyError, ValueError) as exc:
            errors.append(arm + ': ' + str(exc))
    try:
        from gui_agent_bench.task_runtime import runtime
        from gui_agent_bench.task_package import discover
        from gui_agent_bench.preflight import verify_task
        from gui_agent_bench.reference import validate

        for task in discover(root):
            verify_task(root, task)
            runtime(root / 'tasks' / task)
            metadata = tomllib.loads((root / 'tasks' / task / 'task.toml').read_text())['metadata']
            for arm in metadata['eligible_arms']:
                validate(task, arm, root)
    except (OSError, KeyError, ValueError, RuntimeError) as exc:
        errors.append('Task inputs: ' + str(exc))
    for module in ('codex_config', 'cursor_config', 'claude_config'):
        try:
            imported = __import__('gui_agent_bench.runners.' + module, fromlist=['validate_lock'])
            imported.validate_lock(root)
        except (OSError, KeyError, ValueError) as exc:
            errors.append(module + ': ' + str(exc))
    return errors


def main():
    import argparse

    argparse.ArgumentParser(description=__doc__).parse_args()
    errors = check()
    print(
        json.dumps(
            {
                'status': 'fail' if errors else 'pass',
                'arm_count': len(ARM_IDS),
                'scope': 'Static source, policy and task-input validation',
                'errors': errors,
            },
            indent=2,
        )
    )
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
