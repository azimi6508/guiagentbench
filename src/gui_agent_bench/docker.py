"""Docker CLI boundary: argument arrays, isolated containers, explicit cleanup."""

import json
import os
from pathlib import Path
import subprocess


AGENT_IMAGE = 'gui-agent-bench-public-agent:1'
WORKER_IMAGE = 'gui-agent-bench-public-worker:1'
ORACLE_IMAGE = 'gui-agent-bench-public-oracle:1'
ORACLE_BROWSER_IMAGE = 'gui-agent-bench-public-oracle-browser:1'


def docker(*args: str, timeout: int = 120, check: bool = True, env=None, include_stderr=False) -> str:
    result = subprocess.run(
        ['docker', *map(str, args)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=timeout,
        env=env,
    )
    if check and result.returncode:
        # Commands never contain secret values; do not interpolate environment here.
        raise RuntimeError(f'Docker {args[0]} failed: {result.stderr[-2000:]}')
    return (result.stdout + (result.stderr if include_stderr else '')).strip()


def mount(source: Path, destination: str, *, writable: bool = False) -> list[str]:
    source = source.resolve()
    if ',' in str(source):
        raise ValueError('commas are not supported in Docker bind source paths')
    return ['--mount', f'type=bind,source={source},target={destination}' + ('' if writable else ',readonly')]


def isolation(*, memory: str = '1g') -> list[str]:
    return [
        '--read-only',
        '--cap-drop=ALL',
        '--security-opt=no-new-privileges',
        '--pids-limit=256',
        '--cpus=2',
        f'--memory={memory}',
        '--tmpfs',
        '/tmp:rw,nosuid,nodev,size=512m,mode=1777',
    ]


def inspect(name: str) -> dict:
    return json.loads(docker('inspect', name))[0]


def build(root: Path, task_id=None, runner="opencode", app_only=False):
    from gui_agent_bench.task_runtime import runtime
    from gui_agent_bench.task_package import discover, task_path, integration, verify

    if task_id is not None and task_id not in discover(root):
        raise ValueError('unknown task')
    applications = [task_id] if task_id else []
    builds = [
        (AGENT_IMAGE, root / 'runtime/agent', None),
        (WORKER_IMAGE, root, root / 'runtime/worker/Dockerfile'),
        (ORACLE_IMAGE, root, root / 'runtime/oracle/Dockerfile'),
        (ORACLE_BROWSER_IMAGE, root, root / 'runtime/oracle-browser/Dockerfile'),
    ]
    if runner not in {"opencode", "codex", "cursor", "claude", "all"}:
        raise ValueError("Unknown runner")
    if runner in {"codex", "cursor", "claude"}:
        builds = [b for b in builds if b[0] != AGENT_IMAGE]
    builds = [(*b, None) for b in builds]
    if runner in {"codex", "all"}:
        from gui_agent_bench.runners.codex_config import IMAGES

        builds += [(image, root, root / "runtime/codex/Dockerfile", target) for target, image in IMAGES.items()]
    if runner in {"cursor", "all"}:
        from gui_agent_bench.runners.cursor_config import IMAGES as CURSOR_IMAGES

        builds += [(image, root, root / "runtime/cursor/Dockerfile", target) for target, image in CURSOR_IMAGES.items()]
    if runner in {"claude", "all"}:
        from gui_agent_bench.runners.claude_config import IMAGES as CLAUDE_IMAGES

        builds += [(image, root, root / "runtime/claude/Dockerfile", target) for target, image in CLAUDE_IMAGES.items()]
    if app_only:
        builds = []
    for name in applications:
        task = task_path(root, name)
        verify(task)
        settings = integration(task)
        context = root if settings.get('build_context', 'task') == 'checkout' else task / 'environment'
        dockerfile = (
            root / settings['dockerfile'] if context == root else context / settings.get('dockerfile', 'Dockerfile')
        )
        from gui_agent_bench.io import regular_file

        regular_file(dockerfile, context)
        builds.append((runtime(task)['app_image'], context, dockerfile, None))
    for image, context, dockerfile, target in builds:
        print(f'Building {image}', flush=True)
        command = ['docker', 'build', '--tag', image]
        if target:
            command.extend(['--platform', 'linux/amd64', '--target', target])
        if dockerfile:
            command.extend(['--file', str(dockerfile)])
        subprocess.run([*command, str(context)], check=True, timeout=1800)


def provider_environment() -> dict:
    # Pass Docker transport requirements and the one selected credential only.
    allowed = {
        'PATH',
        'SYSTEMROOT',
        'WINDIR',
        'TEMP',
        'TMP',
        'USERPROFILE',
        'HOME',
        'DOCKER_HOST',
        'DOCKER_CONTEXT',
        'DOCKER_CONFIG',
        'DOCKER_TLS_VERIFY',
        'DOCKER_CERT_PATH',
        'OPENROUTER_API_KEY',
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def client_environment() -> dict:
    """Docker client transport only; never inherit provider credentials/proxies."""
    allowed = {
        'PATH',
        'HOME',
        'DOCKER_HOST',
        'DOCKER_CONTEXT',
        'DOCKER_CONFIG',
        'DOCKER_TLS_VERIFY',
        'DOCKER_CERT_PATH',
        'XDG_RUNTIME_DIR',
    }
    return {key: value for key, value in os.environ.items() if key in allowed}
