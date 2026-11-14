"""Actual-account relay startup control. Lists models; never starts inference."""

import argparse
import base64
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    from gui_agent_bench.docker import docker, isolation, client_environment
    from gui_agent_bench.io import dump
    from gui_agent_bench.runners.cursor_config import IMAGES
    from gui_agent_bench.runners.cursor_auth import access_token

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cursor-auth-dir', type=Path)
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.relative_to(ROOT)
    folder.mkdir(parents=True, exist_ok=False)
    prefix = 'gab-cursor-relay-' + uuid.uuid4().hex[:12]
    net = prefix + '-net'
    gateway = prefix + '-gateway'
    client = prefix + '-client'
    report = dict(schema='cursor-relay-control-v1', status='failed', real_inference_started=False)
    created = []
    network = False
    try:
        token = access_token(args.cursor_auth_dir, root=ROOT)
        docker('network', 'create', '--internal', net)
        network = True
        created.append(gateway)
        env = dict(client_environment(), GAB_CURSOR_ACCESS_TOKEN=token)
        docker(
            'create',
            '--name',
            gateway,
            '--network',
            net,
            '--network-alias',
            'provider',
            *isolation(),
            '--user',
            f'{os.getuid()}:{os.getgid()}',
            '--env',
            'GAB_CURSOR_ACCESS_TOKEN',
            '--env',
            'GAB_CURSOR_MODEL=' + args.model,
            IMAGES['gateway'],
            env=env,
        )
        docker('network', 'connect', 'bridge', gateway)
        docker('start', gateway)

        def part(value):
            return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')

        dummy = part({'alg': 'HS256'}) + '.' + part({'sub': 'bench', 'exp': 4102444800}) + '.bench'
        env = dict(client_environment(), CURSOR_AUTH_TOKEN=dummy)
        created.append(client)
        docker(
            'create',
            '--name',
            client,
            '--network',
            net,
            *isolation(),
            '--user',
            f'{os.getuid()}:{os.getgid()}',
            '--tmpfs',
            f'/run:rw,nosuid,nodev,size=512m,mode=0700,uid={os.getuid()},gid={os.getgid()}',
            '--env',
            'CURSOR_AUTH_TOKEN',
            '--entrypoint',
            '/opt/cursor/cursor-agent',
            IMAGES['agent'],
            '--endpoint',
            'http://provider:8080',
            'models',
            env=env,
        )
        output = docker('start', '--attach', client, timeout=90)
        (folder / 'model-list.txt').write_text(output + '\n')
        from gui_agent_bench.docker import inspect

        if inspect(client)['State']['ExitCode'] != 0:
            raise ValueError('Client inventory failed')
        report['status'] = 'passed'
    except Exception as exc:
        from gui_agent_bench.failures import issue

        report['failure'] = issue(exc, phase='setup', operation='cursor_relay_control', impact='zero_credit')
    finally:
        if gateway in created:
            try:
                from gui_agent_bench.runners.cursor_logs import collect_gateway_logs, validate_streams

                collect_gateway_logs(
                    gateway,
                    folder / 'provider.ndjson',
                    folder / 'provider-stderr.log',
                    folder / 'provider-streams.json',
                )
                rows = validate_streams(
                    folder / 'provider.ndjson', folder / 'provider-stderr.log', folder / 'provider-streams.json'
                )
                from gui_agent_bench.cursor_audit import validate_provider_records

                validate_provider_records(rows)
                report['requests'] = [{k: r.get(k) for k in ('path', 'outcome', 'status')} for r in rows]
            except Exception:
                report['status'] = 'failed'
        for name in reversed(created):
            docker('rm', '-f', name, check=False)
        if network:
            docker('network', 'rm', net, check=False)
        dump(folder / 'control.json', report)
    print(json.dumps(report, indent=2))
    return int(report['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
