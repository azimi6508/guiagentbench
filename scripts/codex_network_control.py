#!/usr/bin/env python3
"""Actual Docker network/proxy controls with no credentials or inference."""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

CLIENT = r'''
import json,socket,sys
def denied(host,port):
 try:
  c=socket.create_connection((host,port),timeout=2);c.close();return False
 except OSError:return True
def tunnel(request):
 with socket.create_connection(('egress',8080),timeout=5) as c:
  c.settimeout(20);c.sendall(request.encode());return c.recv(1024).split(b'\r\n',1)[0].decode()
negative={}
for authority in ['example.com:443','127.0.0.1:443','169.254.169.254:443','chatgpt.com:80',
                  'chatgpt.com.evil.invalid:443','auth.openai.com@127.0.0.1:443','browser:8081']:
 negative[authority]=tunnel('CONNECT '+authority+' HTTP/1.1\r\nHost: '+authority+'\r\n\r\n')=='HTTP/1.1 403 Forbidden'
negative['plain_http']=tunnel('GET http://chatgpt.com/ HTTP/1.1\r\nHost: chatgpt.com\r\n\r\n')=='HTTP/1.1 403 Forbidden'
negative['credential_header']=tunnel('CONNECT chatgpt.com:443 HTTP/1.1\r\nProxy-Authorization: synthetic-header-canary\r\n\r\n')=='HTTP/1.1 403 Forbidden'
positive=tunnel('CONNECT chatgpt.com:443 HTTP/1.1\r\nHost: chatgpt.com:443\r\n\r\n')=='HTTP/1.1 200 Connection Established'
print(json.dumps({'direct_external_denied':denied('1.1.1.1',443),
                  'direct_gui_denied':denied(sys.argv[1],8081),
                  'proxy_denials':negative,'allowed_tls_tunnel':positive}))
'''


def control():
    from gui_agent_bench.docker import client_environment, docker, inspect, isolation
    from gui_agent_bench.runners.codex_config import IMAGES
    from gui_agent_bench.runners.codex_security import options, policy

    prefix = 'gab-codex-network-' + uuid.uuid4().hex[:12]
    containers, networks = [], []
    report = dict(
        schema='codex-network-control-v1', status='failed', container_policy=policy(), inference_started=False
    )
    try:
        for suffix in ['inference', 'gui']:
            name = prefix + '-' + suffix
            networks.append(name)
            docker('network', 'create', '--internal', name)
        proxy, gui, agent = [prefix + '-' + r for r in ['proxy', 'gui-sink', 'agent']]
        containers.append(proxy)
        docker(
            'create',
            '--name',
            proxy,
            '--network',
            networks[0],
            '--network-alias',
            'egress',
            *isolation(),
            '--user',
            f'{os.getuid()}:{os.getgid()}',
            IMAGES['egress'],
        )
        docker('network', 'connect', 'bridge', proxy)
        docker('start', proxy)
        containers.append(gui)
        docker(
            'create',
            '--name',
            gui,
            '--network',
            networks[1],
            *isolation(),
            '--user',
            f'{os.getuid()}:{os.getgid()}',
            '--entrypoint',
            '/usr/local/bin/python',
            IMAGES['bridge'],
            '-m',
            'http.server',
            '8081',
        )
        docker('start', gui)
        ip = inspect(gui)['NetworkSettings']['Networks'][networks[1]]['IPAddress']
        containers.append(agent)
        docker(
            'create',
            '--name',
            agent,
            '--network',
            networks[0],
            *isolation(),
            *options(),
            '--user',
            f'{os.getuid()}:{os.getgid()}',
            '--env',
            'HTTPS_PROXY=http://egress:8080',
            '--entrypoint',
            '/usr/local/bin/python',
            IMAGES['agent'],
            '-c',
            CLIENT,
            ip,
        )
        result = docker(
            'start', '--attach', agent, timeout=60, check=False, include_stderr=True, env=client_environment()
        )
        report['client_output'] = result
        report['exit_code'] = inspect(agent)['State']['ExitCode']
        if report['exit_code'] == 0:
            data = json.loads(result)
            report['checks'] = data
            if (
                data['direct_external_denied']
                and data['direct_gui_denied']
                and data['allowed_tls_tunnel']
                and all(data['proxy_denials'].values())
            ):
                report['status'] = 'passed'
    finally:
        for name in reversed(containers):
            if name.endswith('-proxy'):
                log = docker('logs', name, check=False, include_stderr=True)
                report['proxy_log'] = log
                if 'synthetic-header-canary' in log:
                    report['status'] = 'failed'
            docker('rm', '-f', name, check=False)
        for name in reversed(networks):
            docker('network', 'rm', name, check=False)
        report['cleanup'] = not docker('ps', '-aq', '--filter', 'name=' + prefix)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = control()
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: report[k] for k in ['status', 'cleanup', 'inference_started']}))
    raise SystemExit(0 if report['status'] == 'passed' else 1)
