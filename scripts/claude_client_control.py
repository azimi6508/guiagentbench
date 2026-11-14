"""Run one credential-free actual Claude Code CLI/MCP control; no evaluated inference.

The pinned client runs in its production image and talks to the production
gateway, which relays to a scripted upstream with a synthetic credential.
Negative modes prove that a native tool request is refused by the capture
policy and that an upstream 429 is never replayed.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    from gui_agent_bench.docker import docker, isolation, mount, client_environment
    from gui_agent_bench.io import dump, digest
    from gui_agent_bench.runners.base import AuthoringContext
    from gui_agent_bench.runners.registry import resolve
    from gui_agent_bench.runners.claude_config import IMAGES, render, budget
    from gui_agent_bench.runners.claude_protocol import capture
    from gui_agent_bench.runners.claude import gateway_environment, export_file
    from gui_agent_bench.runners.cursor_logs import collect_gateway_logs

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--arm', default='judge_visual')
    parser.add_argument('--platform', choices=['web', 'mobile', 'tv'], default='web')
    parser.add_argument('--profile', choices=['generic', 'native_extended'], default='generic')
    parser.add_argument('--auth-kind', choices=['api_key', 'oauth'], default='api_key')
    parser.add_argument('--mode', choices=['normal', 'zero_calls', 'native_tool', 'rate_limit'], default='normal')
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    for name in ('workspace', 'output', 'config', 'logs/bridge', 'logs/agent'):
        (folder / name).mkdir(parents=True, exist_ok=True)
    (folder / 'workspace/output').mkdir()
    text = b'Use bench_list_files once, then finish.'
    (folder / 'workspace/instruction.md').write_bytes(text)
    from PIL import Image

    Image.new('RGB', (800, 600), 'purple').save(folder / 'workspace/screen.png')
    manifest = {
        'arm': args.arm,
        'platform': args.platform,
        'files': {'instruction.md': digest(text), 'screen.png': digest((folder / 'workspace/screen.png').read_bytes())},
    }
    context = AuthoringContext(
        uuid.uuid4().hex[:16],
        args.arm,
        args.platform,
        (800, 600),
        folder / 'workspace',
        manifest,
        folder / 'output',
        folder / 'config',
        folder / 'logs/agent',
        'unused',
        None,
        120,
        args.profile,
    )
    spec = resolve('claude/claude-fixture-model', reasoning_effort='medium')
    policy = render(context.config_directory, spec, context, args.auth_kind)
    steps = [
        {'name': 'bench_list_files', 'arguments': {}},
        {'name': 'bench_read_file', 'arguments': {'path': '/workspace/instruction.md'}},
        {'name': 'bench_read_image', 'arguments': {'path': '/workspace/screen.png'}},
        {
            'name': 'bench_write_file',
            'arguments': {'path': '/workspace/output/control.txt', 'content': 'synthetic control'},
        },
    ]
    if args.arm != 'judge_visual':
        steps.append({'name': 'gui_observe', 'arguments': {}})
    if 'gui_dump_ui' in policy['tools']:
        steps.append({'name': 'gui_dump_ui', 'arguments': {}})
    if args.mode == 'zero_calls':
        steps = []
    elif args.mode == 'native_tool':
        steps = [{'name': 'native:Bash', 'arguments': {'command': 'id'}}]
    dump(context.config_directory / 'control-steps.json', steps)
    (context.config_directory / 'control-mode').write_text(args.mode)
    (context.config_directory / 'control.png').write_bytes((folder / 'workspace/screen.png').read_bytes())
    limits = budget(context.arm, context.timeout_seconds)
    prefix = 'gab-claude-control-' + context.trial_id
    containers, networks, process = [], [], None
    report = {
        'schema': 'claude-client-control-v1',
        'status': 'failed',
        'real_inference_started': False,
        'arm': args.arm,
        'platform': args.platform,
        'environment_profile': args.profile,
        'auth_kind': args.auth_kind,
        'mode': args.mode,
    }
    try:
        with tempfile.TemporaryDirectory(prefix='gab-claude-control-') as ipc:
            net = prefix + '-net'
            networks.append(net)
            docker('network', 'create', '--internal', net)

            def create(suffix, *more, env=None):
                report['stage'] = 'create-' + suffix
                name = prefix + '-' + suffix
                containers.append(name)
                docker('create', '--name', name, '--user', f'{os.getuid()}:{os.getgid()}', *isolation(), *more, env=env)
                docker('start', name)
                return name

            create(
                'provider',
                '--network',
                net,
                '--network-alias',
                'upstream',
                *mount(ROOT / 'runtime/claude/fixture_provider.py', '/fixture-provider.py'),
                *mount(context.config_directory, '/policy'),
                '--entrypoint',
                'python',
                IMAGES['gateway'],
                '/fixture-provider.py',
            )
            settings = gateway_environment(spec, policy, limits)
            create(
                'gateway',
                '--network',
                net,
                '--network-alias',
                'provider',
                *[a for k, v in settings.items() for a in ('--env', k + '=' + v)],
                *mount(ROOT / 'runtime/claude/gateway_fixture.py', '/gateway-fixture.py'),
                '--entrypoint',
                'python',
                IMAGES['gateway'],
                '/gateway-fixture.py',
            )
            stub_args, stub_command = [], []
            if args.arm != 'judge_visual':
                stub_args = [
                    '--add-host',
                    'browser:127.0.0.1',
                    *mount(ROOT / 'runtime/cursor/control_bridge.py', '/fixture-bridge.py'),
                    '--entrypoint',
                    'python',
                ]
                stub_command = ['/fixture-bridge.py']
            create(
                'bridge',
                '--network',
                'none',
                *mount(context.public_workspace, '/workspace'),
                *mount(context.output_directory, '/workspace/output', writable=True),
                *mount(context.config_directory, '/policy'),
                *mount(folder / 'logs/bridge', '/audit', writable=True),
                *mount(Path(ipc), '/ipc', writable=True),
                *stub_args,
                IMAGES['bridge'],
                *stub_command,
            )
            deadline = time.monotonic() + 15
            while not (Path(ipc) / 'bench.sock').exists():
                if time.monotonic() > deadline:
                    raise ValueError('Bridge did not start')
                time.sleep(0.1)
            agent = prefix + '-agent'
            containers.append(agent)
            report['stage'] = 'create-agent'
            docker(
                'create',
                '--name',
                agent,
                '--user',
                f'{os.getuid()}:{os.getgid()}',
                *isolation(),
                '--network',
                net,
                '--security-opt',
                'apparmor=docker-default',
                '--tmpfs',
                f'/run:rw,nosuid,nodev,size=512m,mode=0700,uid={os.getuid()},gid={os.getgid()}',
                *mount(context.config_directory, '/policy'),
                *mount(Path(ipc), '/ipc'),
                IMAGES['agent'],
            )
            process = subprocess.Popen(
                ['docker', 'start', '--attach', agent],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=client_environment(),
            )
            report['stage'] = 'capture'
            report['summary'] = capture(process, context.log_directory, limits, policy)
            report['status'] = 'passed'
    except Exception as exc:
        report['error_type'] = type(exc).__name__
        from gui_agent_bench.failures import cause_of

        report['cause'] = cause_of(exc)
    finally:
        agent = prefix + '-agent'
        if agent in containers:
            for name in ('mcp.ndjson', 'guard.ndjson', 'child.json'):
                try:
                    export_file(agent, '/run/' + name, folder / 'logs/agent' / name, optional=True)
                except Exception:
                    pass
        for name in containers:
            role = name.rsplit('-', 1)[-1]
            if role in {'gateway', 'provider'}:
                try:
                    collect_gateway_logs(
                        name,
                        folder / (role + '.log'),
                        folder / (role + '-stderr.log'),
                        folder / (role + '-streams.json'),
                        contract='claude-provider-streams-v1',
                    )
                    if (folder / (role + '-stderr.log')).stat().st_size:
                        report.update(status='failed', unexpected_stderr=role)
                except Exception:
                    report.update(status='failed', log_collection_failed=role)
            else:
                (folder / (role + '.log')).write_text(docker('logs', name, check=False, include_stderr=True) + '\n')
            docker('rm', '-f', name, check=False)
        for name in networks:
            docker('network', 'rm', name, check=False)
        if process:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        verify(report, folder, policy, steps, manifest, args)
        dump(folder / 'control.json', report)
    print(json.dumps(report, indent=2))
    return int(report['status'] != 'passed')


def upstream_rows(folder):
    path = folder / 'provider.log'
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def gateway_rows(folder):
    path = folder / 'gateway.log'
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def verify(report, folder, policy, steps, manifest, args):
    """Turn the expected outcome of each mode into a pass/fail control result."""
    upstream, gateway = upstream_rows(folder), gateway_rows(folder)
    report['upstream_requests'] = len(upstream)
    report['gateway_records'] = len(gateway)
    try:
        if not upstream or not all(r['credential_injected'] for r in upstream):
            raise ValueError('Gateway did not inject the credential on every upstream request')
        if any(r['tools'] != sorted(policy['tool_names']) or r['model'] != policy['model'] for r in upstream):
            raise ValueError('Upstream saw tools or a model outside the policy')
        if args.mode == 'rate_limit':
            # Exactly one upstream attempt: neither the client nor the gateway replays it.
            if report['status'] == 'passed' or len(upstream) != 1:
                raise ValueError('Rate-limited request was replayed or admitted')
            if [r.get('status') for r in gateway if r.get('event') == 'request'] != [429]:
                raise ValueError('Gateway did not record the single rate-limited request')
            report.update(status='passed', expected_failure=report.pop('cause', None))
            return
        if args.mode == 'native_tool':
            if report['status'] == 'passed' or report.get('cause') != 'policy_violation':
                raise ValueError('Native tool request was not refused by the capture policy')
            report.update(status='passed', expected_failure=report.pop('cause'))
            return
        if report['status'] != 'passed':
            raise ValueError('Control did not complete')
        from gui_agent_bench.claude_audit import reconcile
        from gui_agent_bench.runners.claude import validate_provider

        report['reconciliation'] = reconcile(folder, policy, args.platform)
        if report['reconciliation']['delivered_tools'] != len(steps):
            raise ValueError('Control did not deliver every scripted call')
        validate_provider(gateway)
        received = [r for row in upstream for r in row['results']]
        images = [r for r in received if r['type'] == 'image']
        if (
            len([r for r in received if r['type'] == 'end']) != len(steps)
            or (steps and not images)
            or any(r['sha256'] != manifest['files']['screen.png'] for r in images)
        ):
            raise ValueError('Upstream did not receive the original image/tool results')
        if steps and (folder / 'output/control.txt').read_text() != 'synthetic control':
            raise ValueError('Scripted artifact was not written')
        report['original_images_received_by_provider'] = len(images)
    except Exception as exc:
        report.update(status='failed', verification_error=str(exc)[:300])


if __name__ == '__main__':
    raise SystemExit(main())
