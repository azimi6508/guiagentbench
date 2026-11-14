#!/usr/bin/env python3
"""Actual bridge/agent-shim Docker control, with synthetic inputs and no auth."""
import base64
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def control():
    from gui_agent_bench.docker import docker, isolation, mount, client_environment
    from gui_agent_bench.io import digest, strict_json
    from gui_agent_bench.runners.codex_config import IMAGES

    name = 'gab-codex-transport-' + uuid.uuid4().hex[:12]
    containers = []
    outcomes = []
    with tempfile.TemporaryDirectory(prefix='gab-transport-') as folder:
        root = Path(folder)
        for sub in ['workspace', 'workspace/output', 'output', 'policy', 'audit', 'ipc']:
            (root / sub).mkdir(parents=True, exist_ok=True)
        text = ('🧑🏽‍💻e\u0301' + ('x' * 17000)).encode()
        (root / 'workspace/instruction.md').write_bytes(text)
        from PIL import Image
        import io

        png = io.BytesIO()
        Image.new('RGB', (960, 640), 'purple').save(png, format='PNG')
        image = png.getvalue()
        (root / 'workspace/screen.png').write_bytes(image)
        manifest = {
            'arm': 'judge_visual',
            'platform': 'web',
            'files': {'instruction.md': digest(text), 'screen.png': digest(image)},
        }
        (root / 'policy/bridge.json').write_text(
            json.dumps(dict(arm='judge_visual', platform='web', viewport=[960, 640], manifest=manifest))
        )
        process = None
        try:
            containers.append(name + '-bridge')
            docker(
                'create',
                '--name',
                containers[-1],
                '--network',
                'none',
                *isolation(),
                '--user',
                f'{os.getuid()}:{os.getgid()}',
                *mount(root / 'workspace', '/workspace'),
                *mount(root / 'output', '/workspace/output', writable=True),
                *mount(root / 'policy', '/policy'),
                *mount(root / 'audit', '/audit', writable=True),
                *mount(root / 'ipc', '/ipc', writable=True),
                IMAGES['bridge'],
            )
            docker('start', containers[-1])
            deadline = time.monotonic() + 20
            while not (root / 'ipc/bench.sock').exists():
                if time.monotonic() > deadline:
                    raise RuntimeError('Bridge socket did not start')
                time.sleep(0.05)
            containers.append(name + '-shim')
            docker(
                'create',
                '--name',
                containers[-1],
                '--interactive',
                '--network',
                'none',
                *isolation(),
                '--user',
                f'{os.getuid()}:{os.getgid()}',
                *mount(root / 'ipc', '/ipc'),
                '--entrypoint',
                '/usr/local/bin/python',
                IMAGES['agent'],
                '/opt/bench/mcp_stdio_client.py',
            )
            process = subprocess.Popen(
                ['docker', 'start', '--attach', '--interactive', containers[-1]],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=client_environment(),
            )
            selection = selectors.DefaultSelector()
            selection.register(process.stdout, selectors.EVENT_READ)
            tail = b''
            seq = 0

            def rpc(method, params, notify=False):
                nonlocal seq, tail
                seq += 1
                frame = {'jsonrpc': '2.0', 'method': method, 'params': params}
                if not notify:
                    frame['id'] = seq
                process.stdin.write(json.dumps(frame).encode() + b'\n')
                process.stdin.flush()
                if notify:
                    return
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if b'\n' not in tail:
                        if not selection.select(0.1):
                            continue
                        chunk = os.read(process.stdout.fileno(), 65536)
                        if not chunk:
                            raise RuntimeError('Unexpected shim EOF')
                        tail += chunk
                        continue
                    line, tail = tail.split(b'\n', 1)
                    value = strict_json(line)
                    if value.get('id') == seq:
                        return value
                raise RuntimeError('MCP control timeout')

            init = rpc(
                'initialize',
                {
                    'protocolVersion': '2025-11-25',
                    'capabilities': {},
                    'clientInfo': {'name': 'qualification', 'version': '1'},
                },
            )
            assert set(init['result']['capabilities']) <= {'tools', 'experimental'}
            rpc('notifications/initialized', {}, True)
            offered = rpc('tools/list', {})['result']['tools']
            assert len(offered) == 4
            outcomes.append('exact_judge_visual_catalog')
            pages = b''
            offset = 0
            while True:
                value = rpc(
                    'tools/call',
                    {'name': 'bench_read_file', 'arguments': {'path': '/workspace/instruction.md', 'offset': offset}},
                )['result']
                assert value['_meta']['gui_agent_bench.bridge_call_id']
                page = json.loads(value['content'][0]['text'])
                pages += page['text'].encode()
                if page['eof']:
                    break
                offset = page['next_offset']
            assert pages == text
            outcomes.append('unicode_long_line_pagination')
            value = rpc('tools/call', {'name': 'bench_read_image', 'arguments': {'path': '/workspace/screen.png'}})[
                'result'
            ]
            assert base64.b64decode(value['content'][0]['data']) == image
            outcomes.append('original_image_and_meta')
            value = rpc(
                'tools/call',
                {
                    'name': 'bench_write_file',
                    'arguments': {'path': '/workspace/output/scratch', 'content': '\x01' * 65536},
                },
            )['result']
            assert not value['isError'] and (root / 'output/scratch').read_bytes() == b'\x01' * 65536
            outcomes.append('escaped_large_frame_and_atomic_write')
            for path in ['/run/codex/auth.json', '/proc/self/environ', '/dev/fd/0', '/workspace/output/../escape']:
                value = rpc('tools/call', {'name': 'bench_read_file', 'arguments': {'path': path}})['result']
                assert value['isError']
            outcomes.append('auth_proc_fd_traversal_denied')
            value = rpc('resources/read', {'uri': 'file:///run/codex/auth.json'})
            assert 'error' in value
            outcomes.append('resource_uri_denied')
            value = rpc('tools/call', {'name': 'unknown', 'arguments': {}})['result']
            assert value['isError']
            outcomes.append('unknown_tool_denied')
            process.stdin.close()
            process.wait(timeout=10)
            assert process.returncode == 0
            outcomes.append('readonly_socket_mount_and_eof_drain')
            selection.close()
            return {
                'schema': 'codex-transport-control-v1',
                'status': 'passed',
                'controls': outcomes,
                'inference_started': False,
            }
        finally:
            for name in reversed(containers):
                docker('rm', '-f', name, check=False)
            if process and process.poll() is None:
                process.kill()
                process.wait()


if __name__ == '__main__':
    print(json.dumps(control(), indent=2))
