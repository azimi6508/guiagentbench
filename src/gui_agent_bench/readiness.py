"""Controller-only browser readiness/protocol check before agent startup."""

import json
import time
import urllib.request

from gui_agent_bench.broker import TOOLS, platform_tools


def main(arm='judge_test', timeout=25, execute=False, platform=None, profile="generic"):
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen('http://browser:8081/health', timeout=2) as response:
                health = json.load(response)
                served_platform = health.get('platform', 'web')
                if (
                    health.get('ready') is not True
                    or set(health) - {'ready', 'platform'}
                    or served_platform not in {'web', 'mobile', 'tv'}
                    or platform is not None
                    and platform != served_platform
                ):
                    raise ValueError('unexpected browser health response')
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise RuntimeError('browser broker did not become ready')
            time.sleep(0.25)
    if execute:
        print('browser-ready')
        return
    for method, params in [
        (
            'initialize',
            {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 'preflight', 'version': '1'}},
        ),
        ('tools/list', {}),
    ]:
        request = urllib.request.Request(
            'http://browser:8081/mcp',
            data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).encode(),
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            result = json.load(response)['result']
        from gui_agent_bench.oracle_broker import tools_for

        expected = tools_for(arm) if arm.startswith(('oracle_', 'test_')) else TOOLS
        expected = platform_tools(expected, served_platform, profile)
        if method == 'tools/list' and result != {'tools': expected}:
            raise ValueError('browser tool manifest differs')
    print('browser-ready')


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--arm', default='judge_test')
    parser.add_argument('--timeout', type=int, default=25)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--platform', choices=['web', 'mobile', 'tv'])
    parser.add_argument('--profile', default='generic')
    args = parser.parse_args()
    main(args.arm, args.timeout, args.execute, args.platform, args.profile)
