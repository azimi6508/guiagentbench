"""Run one credential-free actual Cursor CLI/MCP control; no evaluated inference."""

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
    from gui_agent_bench.runners.cursor_config import IMAGES, render, budget
    from gui_agent_bench.runners.cursor_protocol import capture

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--arm', default='judge_visual')
    parser.add_argument('--platform', choices=['web', 'mobile', 'tv'], default='web')
    parser.add_argument('--profile', choices=['generic', 'native_extended'], default='generic')
    parser.add_argument('--zero-calls', action='store_true')
    parser.add_argument('--native_extended-actions', action='store_true')
    parser.add_argument(
        '--gateway',
        action='store_true',
        help='Route the actual client through the production gateway with a credential-free upstream',
    )
    parser.add_argument('--control-delay-ms', type=int, choices=range(0, 10001), default=0)
    args = parser.parse_args()
    if args.native_extended_actions and (
        args.platform != 'mobile' or args.profile != 'native_extended' or args.arm != 'test_ui'
    ):
        parser.error('Extended native actions require mobile test_ui and native_extended profile')
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
        120 if args.control_delay_ms else 30,
        args.profile,
    )
    policy = render(context.config_directory, resolve('cursor/fixture-model'), context)
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
    mobile_actions = [
        {'action': 'open_app', 'app': 'pro expense'},
        {'action': 'long_press', 'x': 360, 'y': 300},
        {'action': 'scroll', 'dx': 300, 'dy': 0, 'x': 360, 'y': 598},
    ]
    if args.native_extended_actions:
        steps.extend({'name': 'gui_step', 'arguments': value} for value in mobile_actions)
    if args.zero_calls:
        steps = []
    dump(context.config_directory / 'control-steps.json', steps)
    if args.control_delay_ms:
        (context.config_directory / 'control-delay-ms').write_text(str(args.control_delay_ms))
    (context.config_directory / 'control.png').write_bytes((folder / 'workspace/screen.png').read_bytes())
    prefix = 'gab-cursor-control-' + context.trial_id
    containers = []
    networks = []
    process = None
    report = {
        'schema': 'cursor-client-control-v1',
        'status': 'failed',
        'real_inference_started': False,
        'arm': args.arm,
        'platform': args.platform,
        'environment_profile': args.profile,
    }
    try:
        with tempfile.TemporaryDirectory(prefix='gab-cursor-control-') as ipc:
            net = prefix + '-net'
            networks.append(net)
            docker('network', 'create', '--internal', net)

            def create(suffix, *more):
                report['stage'] = 'create-' + suffix
                name = prefix + '-' + suffix
                containers.append(name)
                docker('create', '--name', name, '--user', f'{os.getuid()}:{os.getgid()}', *isolation(), *more)
                docker('start', name)
                return name

            create(
                'provider',
                '--network',
                net,
                '--network-alias',
                'upstream' if args.gateway else 'provider',
                *mount(ROOT / 'runtime/cursor/fixture.cjs', '/fixture.cjs'),
                *mount(context.config_directory, '/policy'),
                '--entrypoint',
                '/opt/cursor/node',
                IMAGES['agent'],
                '/fixture.cjs',
            )
            if args.gateway:
                create(
                    'gateway',
                    '--network',
                    net,
                    '--network-alias',
                    'provider',
                    *mount(ROOT / 'runtime/cursor/gateway_fixture.py', '/gateway-fixture.py'),
                    '--entrypoint',
                    'python',
                    IMAGES['gateway'],
                    '/gateway-fixture.py',
                )
            stub_args = []
            stub_command = []
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
            summary = capture(process, context.log_directory, budget(context.arm, context.timeout_seconds))
            report.update(status='passed', summary=summary)
    except Exception as exc:
        report['error_type'] = type(exc).__name__
        from gui_agent_bench.failures import cause_of

        report['cause'] = cause_of(exc)
    finally:
        agent = prefix + '-agent'
        if agent in containers:
            from gui_agent_bench.runners.cursor import export_file

            for name in ('mcp.ndjson', 'guard.ndjson', 'child.json'):
                export_file(agent, '/run/' + name, folder / 'logs/agent' / name, optional=True)
        for name in containers:
            role = name.rsplit('-', 1)[-1]
            if role in {'gateway', 'provider'}:
                try:
                    from gui_agent_bench.runners.cursor_logs import collect_gateway_logs

                    collect_gateway_logs(
                        name,
                        folder / (role + '.log'),
                        folder / (role + '-stderr.log'),
                        folder / (role + '-streams.json'),
                    )
                    if (folder / (role + '-stderr.log')).stat().st_size:
                        report.update(status='failed', cause='incomplete_trajectory')
                except Exception:
                    report.update(status='failed', cause='incomplete_trajectory')
            else:
                (folder / (role + '.log')).write_text(docker('logs', name, check=False, include_stderr=True) + '\n')
            docker('rm', '-f', name, check=False)
        for name in networks:
            docker('network', 'rm', name, check=False)
        if process:
            process.wait(timeout=5)
        if report['status'] == 'passed':
            try:
                import base64
                from gui_agent_bench.cursor_audit import reconcile

                policy = json.loads((folder / 'config/agent.json').read_text())
                report['reconciliation'] = reconcile(folder, policy, args.platform)
                if report['reconciliation']['delivered_tools'] != len(steps):
                    raise ValueError('Control did not deliver the scripted call')
                returned = [
                    r['value']['mcpResult']['success']
                    for r in (json.loads(line) for line in (folder / 'provider.log').read_text().splitlines())
                    if r.get('event') == 'exec_result'
                ]
                images = [
                    base64.b64decode(block['image']['data'], validate=True)
                    for r in returned
                    for block in r['content']
                    if 'image' in block
                ]
                if (
                    len(returned) != len(steps)
                    or (steps and not images)
                    or any(digest(data) != manifest['files']['screen.png'] for data in images)
                ):
                    raise ValueError('Provider did not receive the original image/tool results')
                if args.native_extended_actions:
                    received = [
                        json.loads(block['text']['text']).get('fixture_received')
                        for r in returned
                        for block in r['content']
                        if 'text' in block and block['text']['text'].startswith('{"fixture_received":')
                    ]
                    if not all(value in received for value in mobile_actions):
                        raise ValueError('Extended native action arguments changed in transport')
                    report['native_extended_actions'] = mobile_actions
                if steps and (folder / 'output/control.txt').read_text() != 'synthetic control':
                    raise ValueError('Scripted artifact was not written')
                report['original_images_received_by_provider'] = len(images)
                if args.gateway:
                    from gui_agent_bench.runners.cursor import provider_record_success
                    from gui_agent_bench.runners.cursor_logs import validate_streams

                    rows = validate_streams(
                        folder / 'gateway.log', folder / 'gateway-stderr.log', folder / 'gateway-streams.json'
                    )
                    records = [row for row in rows if 'outcome' in row]
                    if not records or not all(provider_record_success(row) for row in records):
                        raise ValueError('Production gateway recorded an unsuccessful request')
                    from gui_agent_bench.cursor_audit import validate_provider_records

                    validate_provider_records(records)
                    if not any(row['outcome'] == 'trial_catalog_cache' for row in records):
                        raise ValueError('Actual client did not exercise the catalog cache')
                    if args.control_delay_ms and not any(row.get('path') == '/v1/traces' for row in rows):
                        raise ValueError('Long control did not exercise telemetry')
                    report['gateway_records_verified'] = len(records)
            except Exception:
                report.update(status='failed', cause='incomplete_trajectory')
        dump(folder / 'control.json', report)
    print(json.dumps(report, indent=2))
    return int(report['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
