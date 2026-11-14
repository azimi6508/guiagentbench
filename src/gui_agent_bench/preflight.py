"""Host-only prerequisite checks. Never start trials, apps, or provider requests."""

import json
import os
from pathlib import Path
import subprocess
import sys

from gui_agent_bench.arms import generated
from gui_agent_bench.failures import Failure, diagnostics, issue


def command(*args, timeout=20, **kwargs):
    return subprocess.run(
        list(map(str, args)), capture_output=True, text=True, timeout=timeout, check=True, **kwargs
    ).stdout.strip()


def mobile_ready(root):
    # All ADB reads target emulator-5580 after checking its research AVD identity.
    from gui_agent_bench.mobile_driver import safe_device
    from gui_agent_bench.mobile_runtime import verify_runtime

    safe_device()
    verify_runtime(root)


def check_mobile(root):
    from gui_agent_bench.mobile_host import native_python, native_environment

    python = native_python(root)
    if not python.is_file():
        raise FileNotFoundError()
    env = native_environment(root)
    env['PYTHONPATH'] = str(root / 'src')
    command(python, '-m', 'gui_agent_bench.preflight', '--mobile-check', str(root), timeout=180, env=env)


def verify_task(root, task_id):
    from gui_agent_bench.task_package import task_path, verify

    return verify(task_path(root, task_id))


def require_runtime(root, task_id, arm, model):
    """Fail early, with the command that fixes it, when Docker or a required image is unavailable.

    A single evaluation otherwise reaches Docker with a missing image and
    reports only an unclassified operation error.
    """
    from gui_agent_bench.docker import AGENT_IMAGE, WORKER_IMAGE, ORACLE_IMAGE, ORACLE_BROWSER_IMAGE
    from gui_agent_bench.task_runtime import runtime

    if model.startswith('openrouter/'):
        if not os.environ.get('OPENROUTER_API_KEY'):
            raise ValueError(
                'OPENROUTER_API_KEY is not set. Export the provider key in this shell before an openrouter/ run.'
            )
        from gui_agent_bench.fairness import require as require_fairness

        try:
            require_fairness(root, task_id)
        except (ValueError, OSError, KeyError) as exc:
            raise ValueError(
                f'Local qualification for {task_id} is missing or stale. Run: python scripts/qualify_framework.py '
                f'--task {task_id} --install (see docs/runners.md).'
            ) from exc
    live = model != 'reference/solution' or generated(arm)
    images = {WORKER_IMAGE, runtime(Path(root) / 'tasks' / task_id)['app_image']} if live else set()
    runner = 'opencode'
    if model.startswith(('fixture/', 'openrouter/')):
        images.add(AGENT_IMAGE)
    if generated(arm):
        images.update({ORACLE_IMAGE, ORACLE_BROWSER_IMAGE})
    for prefix in ('codex', 'cursor', 'claude'):
        if model.startswith(prefix + '/'):
            from importlib import import_module

            images.update(import_module(f'gui_agent_bench.runners.{prefix}_config').IMAGES.values())
            runner = 'all'
    if not images:
        return
    try:
        engine = command('docker', 'info', '--format', '{{.OSType}}')
    except (OSError, RuntimeError, subprocess.SubprocessError):
        raise ValueError(
            'Docker is not available. Install and start Docker Engine, and check that `docker info` '
            'succeeds for your user.'
        ) from None
    if engine != 'linux':
        raise ValueError('Docker must run Linux containers.')
    missing = []
    for image in sorted(images):
        # The canonical reference keeps this a local inspection; it never pulls.
        reference = f'docker.io/library/{image}' if '/' not in image else image
        try:
            command('docker', 'image', 'inspect', reference, '--format', '{{.Id}}')
        except (OSError, RuntimeError, subprocess.SubprocessError):
            missing.append(image)
    if missing:
        build = 'python scripts/bench.py build' + (' --runner all' if runner == 'all' else '') + f' --task {task_id}'
        raise ValueError(f"Required Docker images are not built: {', '.join(missing)}. Build them with: {build}")


def check(root, manifest, *, credential_source=None, cursor_credential_source=None):
    from gui_agent_bench.docker import AGENT_IMAGE, WORKER_IMAGE, ORACLE_IMAGE, ORACLE_BROWSER_IMAGE
    from gui_agent_bench.task_runtime import runtime
    from gui_agent_bench.gateway import fixture_reply

    checks, failures, platforms = [], [], {}

    def execution_platform(task_id):
        return platforms[task_id]

    def probe(name, action, message, cause='infrastructure_error', **context):
        try:
            action()
            checks.append({'name': name, 'status': 'passed', **context})
            return True
        except Exception as exc:
            # Exception/command text may contain host or credential data. Persist
            # only curated remediation and trusted failure-v1 classifications.
            failure = issue(
                exc if isinstance(exc, Failure) else Failure(cause),
                phase='setup',
                operation=name,
                impact='zero_credit',
                source=context,
            )
            if isinstance(exc, Failure):
                message = str(exc) + ' ' + message
            failures.append(failure)
            checks.append({'name': name, 'status': 'failed', 'message': message, **context})
            return False

    def docker_ready():
        if command('docker', 'info', '--format', '{{.OSType}}') != 'linux':
            raise ValueError('Linux engine required')

    cells = manifest['cells']
    environment_cells = [c for c in cells if c['model'] != 'reference/solution' or generated(c['arm'])]
    docker_ok = (
        probe(
            'docker_engine',
            docker_ready,
            'Docker Linux engine is unavailable. Start a Docker engine with Linux containers and verify docker info succeeds.',
        )
        if environment_cells
        else False
    )
    task_ids = sorted({c['task'] for c in cells})
    environment_tasks = {c['task'] for c in environment_cells}
    images = {WORKER_IMAGE} if environment_cells else set()
    if any(c['model'].startswith(('fixture/', 'openrouter/')) for c in cells):
        images.add(AGENT_IMAGE)
    if any(generated(c['arm']) for c in cells):
        images.add(ORACLE_IMAGE)
        images.add(ORACLE_BROWSER_IMAGE)
    for task_id in task_ids:
        probe(
            'task_inputs',
            lambda t=task_id: verify_task(root, t),
            f'Task inputs are missing or differ from the recorded pins: {task_id}. Restore its prepared source assets.',
            task=task_id,
        )
        if any(c['task'] == task_id and c['model'] not in {'reference/solution', 'fixture/scripted'} for c in cells):
            from gui_agent_bench.fairness import require as require_fairness

            probe(
                'fairness_qualification',
                lambda t=task_id: require_fairness(root, t),
                f'Fairness qualification is missing or stale for {task_id}. Complete the separately recorded reference, boundary and execution controls before model evaluation.',
                cause='capability_unavailable',
                task=task_id,
            )

        def task_runtime(t=task_id):
            config = runtime(root / 'tasks' / t)
            platforms[t] = config['platform']
            image = config['app_image']
            if t in environment_tasks:
                images.add(image)

        probe(
            'task_runtime',
            task_runtime,
            f'Task runtime configuration is invalid: {task_id}. Restore the pinned task configuration.',
            task=task_id,
        )
    if any(item['status'] == 'failed' and item['name'] in {'task_inputs', 'task_runtime'} for item in checks):
        return {'status': 'failed', 'checks': checks, 'diagnostics': diagnostics(failures)}
    if any(c['model'].startswith('codex/') for c in cells):
        from gui_agent_bench.runners.codex_config import IMAGES

        images.update(IMAGES.values())
    if any(c['model'].startswith('cursor/') for c in cells):
        from gui_agent_bench.runners.cursor_config import IMAGES as CURSOR_IMAGES

        images.update(CURSOR_IMAGES.values())
    if any(c['model'].startswith('claude/') for c in cells):
        from gui_agent_bench.runners.claude_config import IMAGES as CLAUDE_IMAGES

        images.update(CLAUDE_IMAGES.values())
    if docker_ok:
        for image in sorted(images):
            # Docker Desktop can list/run local short tags while image inspect
            # rejects them. Use their canonical Docker Hub library reference;
            # this remains a local inspection and never pulls an image.
            reference = f'docker.io/library/{image}' if '/' not in image else image
            probe(
                'docker_image',
                lambda i=reference: command('docker', 'image', 'inspect', i, '--format', '{{.Id}}'),
                f'Could not inspect required Docker image: {image}. Check docker image inspect and the active Docker context; build the selected task image if it is absent.',
                image=image,
            )
    if any(c['model'].startswith('codex/') for c in cells):
        from gui_agent_bench.runners.codex_config import IMAGES, validate_lock
        from gui_agent_bench.runners.codex_auth import source_path, validate_directory
        from gui_agent_bench.runners.codex import require_qualification
        from gui_agent_bench.runners.registry import resolve

        probe(
            'codex_lock',
            lambda: validate_lock(root),
            'Codex runtime source/protocol lock is missing or differs.',
            cause='capability_unavailable',
        )
        probe(
            'codex_auth',
            lambda: validate_directory(source_path(credential_source), [root]),
            'Codex requires a dedicated external 0700 directory with an owned regular 0600 saved ChatGPT auth.json.',
            cause='capability_unavailable',
        )
        for cell in cells:
            if cell['model'].startswith('codex/'):
                probe(
                    'codex_qualification',
                    lambda c=cell: require_qualification(
                        root,
                        resolve(c['model'], reasoning_effort=c.get('agent_spec', {}).get('reasoning_effort', 'medium')),
                        c['arm'],
                        execution_platform(c['task']),
                        'generic',
                    ),
                    'Codex is unavailable until the actual-client and isolated-image boundary qualification passes; run scripts/qualify_codex.py.',
                    cause='capability_unavailable',
                    arm=cell['arm'],
                )
    if any(c['model'].startswith('cursor/') for c in cells):
        from gui_agent_bench.runners.cursor_config import validate_lock as cursor_lock
        from gui_agent_bench.runners.cursor_auth import credentials as cursor_credentials
        from gui_agent_bench.runners.cursor import require_qualification as cursor_qualification
        from gui_agent_bench.runners.registry import resolve

        probe(
            'cursor_lock',
            lambda: cursor_lock(root),
            'Cursor pinned sources are missing or differ.',
            cause='capability_unavailable',
        )
        cursor_source = cursor_credential_source if cursor_credential_source is not None else credential_source
        probe(
            'cursor_auth',
            lambda: cursor_credentials(cursor_source, root=root),
            'Cursor needs CURSOR_API_KEY or a dedicated external CLI login; run scripts/check_cursor_startup.py --login.',
            cause='capability_unavailable',
        )
        for cell in cells:
            if cell['model'].startswith('cursor/'):
                probe(
                    'cursor_qualification',
                    lambda c=cell: cursor_qualification(
                        root, resolve(c['model']), c['arm'], execution_platform(c['task']), 'generic'
                    ),
                    'Cursor needs fresh selected-model boundary qualification; run scripts/qualify_cursor.py.',
                    cause='capability_unavailable',
                    arm=cell['arm'],
                )
    if any(c['model'].startswith('claude/') for c in cells):
        from gui_agent_bench.runners.claude_config import validate_lock as claude_lock
        from gui_agent_bench.runners.claude_auth import credentials as claude_credentials
        from gui_agent_bench.runners.claude import require_qualification as claude_qualification
        from gui_agent_bench.runners.registry import resolve

        probe(
            'claude_lock',
            lambda: claude_lock(root),
            'Claude Code pinned sources are missing or differ.',
            cause='capability_unavailable',
        )
        probe(
            'claude_auth',
            lambda: claude_credentials(),
            'Claude Code needs exactly one of ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN in the environment.',
            cause='capability_unavailable',
        )
        for cell in cells:
            if cell['model'].startswith('claude/'):
                probe(
                    'claude_qualification',
                    lambda c=cell: claude_qualification(
                        root,
                        resolve(c['model'], reasoning_effort=c.get('agent_spec', {}).get('reasoning_effort', 'medium')),
                        c['arm'],
                        execution_platform(c['task']),
                        'generic',
                    ),
                    'Claude Code needs fresh selected-model boundary qualification; run scripts/qualify_claude.py.',
                    cause='capability_unavailable',
                    arm=cell['arm'],
                )
    seen = set()
    for c in cells:
        identity = (c['task'], c['arm'], c['fixture_program'])
        if c['model'] == 'reference/solution' and identity not in seen:
            from gui_agent_bench.reference import validate

            seen.add(identity)
            probe(
                'reference_solution',
                lambda c=c: validate(c['task'], c['arm'], root),
                f"Hand-written reference solution is unavailable for {c['task']} / {c['arm']}.",
                cause='capability_unavailable',
                task=c['task'],
                arm=c['arm'],
            )
            continue
        if c['model'] != 'fixture/scripted' or identity in seen:
            continue
        seen.add(identity)
        from gui_agent_bench.task_package import NEGATIVE_CONTROLS, task_path
        from gui_agent_bench.reference_controls import register_task

        selected_control = (
            c['fixture_program']
            if c['fixture_program'] in NEGATIVE_CONTROLS
            else register_task(task_path(root, c['task']))
        )
        probe(
            'scripted_control',
            lambda c=c: fixture_reply(
                [],
                'PASS',
                manifest.get('fixture_probe', False),
                c['arm'],
                selected_control,
                execution_platform(c['task']),
            ),
            f"Scripted solution is unavailable for {c['task']} / {c['arm']} ({c['fixture_program']}).",
            cause='capability_unavailable',
            task=c['task'],
            arm=c['arm'],
        )
    if any(c['model'].startswith('openrouter/') for c in cells):

        def credential():
            if not os.environ.get('OPENROUTER_API_KEY'):
                raise ValueError()

        probe(
            'provider_credential',
            credential,
            'Set OPENROUTER_API_KEY in the environment before running the selected models.',
        )
    if any(execution_platform(t) == 'mobile' for t in environment_tasks):
        probe(
            'native_runtime',
            lambda: check_mobile(root),
            'Native prerequisites are unavailable or differ from their pins. Prepare .mobile, boot the dedicated research AVD, and run scripts/mobile_setup.py check.',
        )
    for task_id in sorted(t for t in environment_tasks if execution_platform(t) == 'mobile'):

        def installed(t=task_id):
            from gui_agent_bench.mobile_host import native_python, native_environment

            environment = native_environment(root)
            environment['PYTHONPATH'] = str(root / 'src')
            command(
                native_python(root),
                '-m',
                'gui_agent_bench.preflight',
                '--application-check',
                root,
                t,
                timeout=180,
                env=environment,
            )

        probe(
            'native_application',
            installed,
            'Install the APK pinned by this task using mobile_setup.py install-app.',
            task=task_id,
        )
    return {'status': 'passed' if not failures else 'failed', 'checks': checks, 'diagnostics': diagnostics(failures)}


def print_report(report):
    print(f"Preflight {report['status']}.", flush=True)
    for item in report['checks']:
        if item['status'] == 'failed':
            print('  - ' + item['message'], flush=True)


if __name__ == '__main__':
    if len(sys.argv) in {4, 5} and sys.argv[1] == '--application-install':
        from gui_agent_bench.native_application import install_apk

        print(
            json.dumps(install_apk(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]) if len(sys.argv) == 5 else None))
        )
        raise SystemExit(0)

    if len(sys.argv) == 4 and sys.argv[1] == '--application-check':
        from gui_agent_bench.native_application import verify_installed

        print(json.dumps(verify_installed(Path(sys.argv[2]), sys.argv[3])))
        raise SystemExit(0)

    if len(sys.argv) != 3 or sys.argv[1] != '--mobile-check':
        raise SystemExit(2)
    mobile_ready(Path(sys.argv[2]))
