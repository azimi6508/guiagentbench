"""Start the pinned client with no real credentials or task filesystem mounts."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error


def placeholder():
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')

    return part({'alg': 'HS256', 'typ': 'JWT'}) + '.' + part({'sub': 'bench', 'exp': 4102444800}) + '.bench'


def main():
    policy = json.loads(Path('/policy/agent.json').read_text())
    Path('/run/guard.ndjson').touch(exist_ok=False)
    home = Path('/run/home/.cursor')
    home.mkdir(parents=True, mode=0o700)
    for name in ('cli-config.json', 'mcp.json', 'hooks.json'):
        shutil.copyfile('/policy/' + name, home / name)
    os.environ['CURSOR_AUTH_TOKEN'] = placeholder()
    os.environ['CURSOR_API_ENDPOINT'] = 'http://provider:8080'
    args = [
        '/opt/cursor/cursor-agent',
        '--endpoint',
        'http://provider:8080',
        '--model',
        policy['model'],
        '--allowed-tools',
        'mcp_tool_call,get_mcp_tools_tool_call',
        '--disable-project-configs',
        '--approve-mcps',
        '--trust',
        '--print',
        '--output-format',
        'stream-json',
    ]
    if sys.argv[1:] == ['catalog'] or policy.get('startup_only'):
        args = ['/opt/cursor/cursor-agent', 'mcp', 'list-tools', 'bench']
    elif sys.argv[1:]:
        raise ValueError('Unknown runtime mode')
    else:
        # The pinned client abandons parameterized catalog resolution after two
        # seconds. Fetch it once before model startup; the per-trial gateway
        # returns that identical bounded response for the identical request.
        # This command starts no inference and its output is not model evidence.
        warm = subprocess.run(
            args + ['--list-models'], env=os.environ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90
        )
        if warm.returncode:
            raise ValueError('Cursor catalog startup failed')
        deadline = time.monotonic() + 30
        while True:
            try:
                with urllib.request.urlopen('http://provider:8080/bench/catalog-ready', timeout=2) as response:
                    if response.status == 200:
                        break
            except urllib.error.HTTPError as exc:
                if exc.code != 503:
                    raise
            if time.monotonic() >= deadline:
                raise ValueError('Cursor parameterized catalog unavailable')
            time.sleep(0.1)
        args.append(policy['instruction'])
    child = subprocess.Popen(args, env=os.environ)
    code = child.wait()
    Path('/run/child.json').write_text(json.dumps({'exit_code': code}))
    print(json.dumps({'type': 'bench_child_exit', 'exit_code': code}), flush=True)
    # Keep tmpfs evidence available to the host until it has been exported.
    deadline = time.monotonic() + 60
    while not Path('/run/shutdown').exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    sys.exit(code)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        sys.stderr.write('Cursor runtime control failed.\n')
        sys.exit(1)
