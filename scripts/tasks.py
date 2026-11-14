"""Create, discover, validate and plan self-contained task packages."""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from gui_agent_bench.io import dump
from gui_agent_bench.task_package import discover, task_path, metadata, verify, seal_manifest, local_file, IDENTIFIER


def create(root, identifier, source):
    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        raise ValueError('Use <domain>/<lowercase-hyphenated-name>')
    if source.split('/')[0] != identifier.split('/')[0]:
        raise ValueError('Clone an example from the same domain')
    original = task_path(root, source)
    verify(original)
    destination = root / 'tasks' / identifier
    if destination.exists() or destination.is_symlink():
        raise ValueError('Destination already exists; nothing was overwritten')
    destination.parent.resolve().relative_to(root.resolve())
    if destination.parent.is_symlink():
        raise ValueError('Task domain directory cannot be a link')
    destination.mkdir(parents=True)
    from gui_agent_bench.task_package import manifest_files
    for relative in manifest_files(original):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(local_file(original, relative, 32_000_000))
        shutil.copymode(original / relative, target)
    slug = identifier.split('/')[1]
    path = destination / 'task.toml'
    text = path.read_text()
    text = re.sub(r'(?m)^[ \t]*name[ \t]*=.*$', 'name = ' + json.dumps('gui-agent-bench/' + slug), text, count=1)
    text = re.sub(r'(?m)^[ \t]*task_id[ \t]*=.*$', 'task_id = ' + json.dumps(slug), text, count=1)
    text = re.sub(r'(?m)^[ \t]*reference_alias[ \t]*=.*$', 'reference_alias = ' + json.dumps(slug), text, count=1)
    path.write_text(text)
    # Shared app fixtures are task-owned, so another AURA behavior needs no
    # global catalog or shared image modification.
    for variant in ('correct', 'faulty'):
        path = destination / 'variants' / variant / 'settings.json'
        value = json.loads(path.read_text())
        if isinstance(value.get('spec'), dict):
            value['spec']['id'] = slug
            dump(path, value)
    seal_manifest(destination)
    verify(destination)
    return destination


def plan(root, identifiers, arms, model, destination):
    result = {'schema': 'run-plan-v1', 'name': 'Task evaluation', 'models': [model], 'tasks': []}
    for identifier in identifiers:
        task = task_path(root, identifier)
        verify(task)
        eligible = metadata(task)['metadata']['eligible_arms']
        chosen = arms or eligible
        if any(a not in eligible for a in chosen):
            raise ValueError('Select only declared eligible arms')
        result['tasks'].append({'task': identifier, 'arms': chosen, 'repeats': 1})
    if destination.exists() or destination.is_symlink():
        raise ValueError('Plan destination already exists')
    from gui_agent_bench.run_plan import prepare
    prepare(root, result, True)  # reject an unknown model or repeated arm before writing
    dump(destination, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list', help='Discover tasks directly from their folders')
    new = commands.add_parser('new', help='Copy a runnable example as a starting point; never overwrite')
    new.add_argument('task')
    new.add_argument('--from', dest='source', required=True)
    for command in ('validate', 'seal'):
        child = commands.add_parser(command)
        child.add_argument('task')
    make_plan = commands.add_parser('plan')
    make_plan.add_argument('tasks', nargs='+')
    make_plan.add_argument('--arms', nargs='+')
    make_plan.add_argument('--model', default='reference/solution')
    make_plan.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == 'list':
            result = {'tasks': list(discover(root))}
        elif args.command == 'new':
            result = {'created': str(create(root, args.task, args.source)),
                      'next': 'Edit the goal, paired fixture, journey and reference programs; then seal and validate.'}
        elif args.command == 'plan':
            result = plan(root, args.tasks, args.arms, args.model, args.output)
        else:
            task = task_path(root, args.task)
            if args.command == 'seal':
                seal_manifest(task)
            result = verify(task)
            from gui_agent_bench.task_runtime import runtime
            result['runtime'] = runtime(task)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'status': 'failed', 'reason': str(error)}, indent=2))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
