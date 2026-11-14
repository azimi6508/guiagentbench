"""Discover and validate trusted task packages without central registration."""

import ast
import copy
from pathlib import Path, PurePosixPath
import re
import tomllib

from gui_agent_bench.arms import ARM_IDS
from gui_agent_bench.io import digest, dump, regular_file, strict_json

ROOT = Path(__file__).resolve().parents[2]
IDENTIFIER = re.compile(r'(web|mobile|tv)/[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z')
GENERATED = tuple(a for a in ARM_IDS if a.startswith(('oracle_', 'test_')))
NEGATIVE_CONTROLS = {'pass', 'fail', 'crash', 'missing', 'forbidden'}


def local_file(task, relative, limit=4_000_000):
    if (
        not isinstance(relative, str)
        or not relative
        or '\\' in relative
        or PurePosixPath(relative).is_absolute()
        or ':' in relative
        or any(p in {'', '.', '..'} for p in relative.split('/'))
    ):
        raise ValueError('Task file paths must be relative and stay inside the package')
    return regular_file(task / relative, task, limit)


def task_path(root, identifier):
    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        raise ValueError('Task ID must be <web|mobile|tv>/<lowercase-hyphenated-name>')
    path = Path(root).absolute() / 'tasks' / identifier
    try:
        regular_file(path / 'task.toml', Path(root).absolute())
    except FileNotFoundError as error:
        raise ValueError('Unknown task: ' + identifier) from error
    return path


def discover(root=ROOT):
    root = Path(root).absolute()
    result = []
    for path in sorted((root / 'tasks').glob('*/*/task.toml')):
        identifier = path.parent.relative_to(root / 'tasks').as_posix()
        try:
            task_path(root, identifier)
        except ValueError as error:
            raise ValueError(f'Invalid task folder tasks/{identifier}: {error}') from error
        result.append(identifier)
    return tuple(result)


def metadata(task):
    value = tomllib.loads(regular_file(task / 'task.toml', task).decode())
    data = value['metadata']
    platform = data['platform']
    domain = data.get('domain', platform)
    identifier = domain + '/' + data['task_id']
    if (
        platform not in {'web', 'mobile', 'tv'}
        or not IDENTIFIER.fullmatch(identifier)
        or task.name != data['task_id']
        or task.parent.name != domain
    ):
        raise ValueError('Task domain and ID must match its directory; declare a supported execution platform')
    arms = data['eligible_arms']
    if not isinstance(arms, list) or not arms or len(set(arms)) != len(arms) or any(a not in ARM_IDS for a in arms):
        raise ValueError('Task must declare unique supported arms')
    if data['platform'] == 'tv' and any(a.endswith('_ui') for a in arms):
        raise ValueError('Remote-only TV packages cannot declare UI arms')
    for name in ('source', 'upstream_id', 'upstream_url', 'upstream_revision', 'license', 'transform_notes'):
        if not isinstance(data.get(name), str) or not data[name].strip():
            raise ValueError('Missing task provenance field: ' + name)
    integration = value.get('integration', {})
    allowed = {
        'environment_profile',
        'build_context',
        'dockerfile',
        'reference',
        'native_application',
        'native_package',
        'native_apk_sha256',
        'native_apk_url',
        'reference_alias',
        'web',
    }
    if not isinstance(integration, dict) or set(integration) - allowed:
        raise ValueError('Unknown task integration settings')
    if integration.get('build_context', 'task') not in {'task', 'checkout'}:
        raise ValueError('Build context must be task or checkout')
    if integration.get('environment_profile', 'generic') not in {'generic', 'mobile', 'tv'}:
        raise ValueError('Unknown environment profile')
    if 'web' in integration:
        from gui_agent_bench.environment import web_preparation

        web_preparation(integration['web'])
    native = {name for name in ('native_application', 'native_package', 'native_apk_sha256') if name in integration}
    if native or data['platform'] == 'mobile':
        if data['platform'] != 'mobile' or len(native) != 3:
            raise ValueError('A native app extension needs its source, package and APK SHA256 together')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+', integration['native_package']):
            raise ValueError('Invalid Android package name')
        if not re.fullmatch(r'[0-9a-f]{64}', integration['native_apk_sha256']):
            raise ValueError('Pin the native application APK with SHA256')
        local_file(task, integration['native_application'], 65_536)
    if 'native_apk_url' in integration:
        from urllib.parse import urlsplit

        url = urlsplit(integration['native_apk_url'])
        if (
            not native
            or url.scheme != 'https'
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError('Declare a credential-free HTTPS APK URL with the application pin')
    return value


def integration(task):
    return metadata(task).get('integration', {})


def manifest_files(task):
    return {
        p.relative_to(task).as_posix(): digest(regular_file(p, task, 32_000_000))
        for p in sorted(task.rglob('*'))
        if (p.is_file() or p.is_symlink())
        and '__pycache__' not in p.parts
        and p.relative_to(task).as_posix() != 'lineage/manifest.json'
    }


def seal_manifest(task):
    data = metadata(task)
    manifest = {
        'schema': 'task-files-v1',
        'task': data['metadata'].get('domain', data['metadata']['platform']) + '/' + data['metadata']['task_id'],
        'files': manifest_files(task),
    }
    dump(task / 'lineage/manifest.json', manifest)
    return manifest


def verify(task):
    data = metadata(task)
    required = [
        'instruction.md',
        'private/labels.json',
        'private/test_source.py',
        'private/gold_test.py',
        'variants/correct/settings.json',
        'variants/faulty/settings.json',
        'tests/test.sh',
    ]
    required += ['arms/' + a + '.md' for a in data['metadata']['eligible_arms'] if a.startswith('judge_')]
    for name in required:
        local_file(task, name)
    if strict_json(local_file(task, 'private/labels.json')) != {'correct': 'PASS', 'faulty': 'FAIL'}:
        raise ValueError('A paired task must label correct PASS and faulty FAIL')
    for variant in ('correct', 'faulty'):
        strict_json(local_file(task, 'variants/' + variant + '/settings.json'))
    manifest = strict_json(local_file(task, 'lineage/manifest.json'))
    expected = manifest_files(task)
    if manifest.get('schema') != 'task-files-v1' or manifest.get('files') != expected:
        raise ValueError('Task files changed; review the change and run tasks.py seal <task>')
    identifier = data['metadata'].get('domain', data['metadata']['platform']) + '/' + data['metadata']['task_id']
    if manifest.get('task') != identifier:
        raise ValueError('Task manifest identity differs')
    if any(a in GENERATED for a in data['metadata']['eligible_arms']):
        load_control(task)
    return {'status': 'pass', 'task': identifier, 'verified_files': len(expected)}


def load_control(task):
    spec = integration(task)
    path = spec.get('reference', 'private/reference.json')
    record = strict_json(local_file(task, path))
    # Programs stay in trusted reference storage. They never enter model workspaces.
    if not isinstance(record, dict) or set(record) - {
        'schema',
        'journey',
        'regions',
        'programs',
        'viewport',
        'initial_delay',
        'action_delay',
        'capture_ui',
        'platform',
    }:
        raise ValueError('Unknown reference control fields')
    record = copy.deepcopy(record)
    data_platform = metadata(task)['metadata']['platform']
    if record.get('platform', data_platform) != data_platform:
        raise ValueError('Reference platform differs from task')
    record['platform'] = data_platform
    if record.pop('schema', None) != 'task-reference-v1':
        raise ValueError('Expected task-reference-v1')
    programs = record.get('programs', {})
    if not isinstance(programs, dict) or set(programs) - set(GENERATED):
        raise ValueError('Reference program keys must name generated arms')
    for arm in metadata(task)['metadata']['eligible_arms']:
        if arm not in GENERATED:
            continue
        filename = programs.get(arm)
        code = local_file(task, filename, 65_536).decode()
        entry = 'test' if arm.startswith('test_') else 'check'
        if not any(isinstance(n, ast.FunctionDef) and n.name == entry for n in ast.parse(code).body):
            raise ValueError(arm + ' reference must export def ' + entry + '(page)')
        programs[arm] = code
    record['programs'] = programs
    from gui_agent_bench.task_runtime import runtime

    config = runtime(task)
    if record.get('viewport') != [config['viewport_width'], config['viewport_height']]:
        raise ValueError('Reference viewport differs from the task runtime')
    from gui_agent_bench.reference_controls import validate_record

    return validate_record(record)
