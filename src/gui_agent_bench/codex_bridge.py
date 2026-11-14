"""Credential-free, manifest-only MCP bridge for Codex authoring.

No generated source is imported or executed here. GUI actions go to the existing
broker through one fixed, closing HTTP connection per request, without retries.
"""

import base64
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import socket
import stat
import tempfile
import threading
import uuid

from gui_agent_bench.arms import ARM_IDS
from gui_agent_bench.broker import TOOLS, platform_tools, schema
from gui_agent_bench.budgets import codex_budget
from gui_agent_bench.coordinates import observation_content
from gui_agent_bench.io import digest, strict_json
from gui_agent_bench.runners.registry import canonical

META = 'gui_agent_bench.bridge_call_id'


class ReadPageSizeError(ValueError):
    """Static public-schema diagnostic; never contains file or exception text."""


def catalog(arm, platform, profile='generic'):
    if profile not in {'generic', 'native_extended'} or (profile == 'native_extended' and platform != 'mobile'):
        raise ValueError('Unavailable environment profile')
    if arm not in ARM_IDS or platform not in {'web', 'mobile', 'tv'} or (platform == 'tv' and arm.endswith('_ui')):
        raise ValueError('Unavailable arm/platform')
    path = {'type': 'string'}
    files = [
        ('bench_list_files', 'List available public inputs and output files.', schema()),
        (
            'bench_read_file',
            'Read an exact UTF-8 byte page: max_bytes is 4..8192 (default 8192). '
            'For larger files, repeat with offset=next_offset until eof=true. Never request the whole file size.',
            schema(
                {
                    'path': path,
                    'offset': {'type': 'integer', 'minimum': 0},
                    'max_bytes': {'type': 'integer', 'minimum': 4, 'maximum': 8192},
                },
                ['path'],
            ),
        ),
        (
            'bench_read_image',
            'Read an original public PNG with pixel coordinate metadata.',
            schema({'path': path}, ['path']),
        ),
        (
            'bench_write_file',
            'Atomically write output text. Does not execute code.',
            schema(
                {
                    'path': path,
                    'content': {'type': 'string'},
                    'expected_sha256': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
                },
                ['path', 'content'],
            ),
        ),
    ]
    result = [dict(name=n, description=d, inputSchema=s) for n, d, s in files]
    if arm == 'judge_visual':
        return result
    if arm == 'judge_test':
        base = TOOLS
    else:
        from gui_agent_bench.oracle_broker import tools_for

        base = tools_for(arm)
    return result + [{**tool, 'name': 'gui_' + tool['name']} for tool in platform_tools(base, platform, profile)]


def virtual(path):
    if (
        not isinstance(path, str)
        or not path.startswith('/workspace/')
        or any(ord(c) < 32 or ord(c) == 127 for c in path)
        or '\\' in path
        or ':' in path
        or str(PurePosixPath(path)) != path
        or any(c in {'.', '..', ''} for c in path.split('/')[1:])
    ):
        raise ValueError('Path denied')
    return path[len('/workspace/') :]


def checked_path(root, relative, *, missing=False):
    cursor = root
    for i, part in enumerate(('', *PurePosixPath(relative).parts)):
        if part:
            cursor = cursor / part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            if missing:
                continue
            raise ValueError('Path denied') from None
        final = cursor == root / relative
        if stat.S_ISLNK(info.st_mode) or (not final and not stat.S_ISDIR(info.st_mode)):
            raise ValueError('Path denied')
        if final and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ValueError('Path denied')
    return cursor


def read_regular(root, relative, limit=4_000_000):
    path = checked_path(root, relative)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError('File denied')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('File budget exceeded')
    return data


class Broker:
    def __init__(self, expected, *, arm=None, platform=None, profile='generic'):
        self.prepared_reset_timeout = (
            180
            if platform == 'mobile' and profile == 'native_extended' and arm in {'oracle_visual', 'oracle_ui'}
            else 60
        )
        self.sequence = 0
        self.request(
            'initialize',
            {
                'protocolVersion': '2024-11-05',
                'capabilities': {},
                'clientInfo': {'name': 'bench-bridge', 'version': '1'},
            },
        )
        self.request('notifications/initialized', {}, notification=True)
        offered = self.request('tools/list', {})
        if offered != {'tools': [{**t, 'name': t['name'][4:]} for t in expected if t['name'].startswith('gui_')]}:
            raise ValueError('GUI catalog differs')

    def request(self, method, params, notification=False):
        self.sequence += 1
        value = dict(jsonrpc='2.0', method=method, params=params)
        if not notification:
            value['id'] = self.sequence
        data = canonical(value)
        if len(data) > 16_384:
            raise ValueError('Broker request budget exceeded')
        # A native oracle reset restores the full prepared journey, which may
        # exceed the ordinary single-operation transport timeout. Keep it within
        # the existing native preparation bound; the outer authoring clock still
        # expires normally and no request or action is repeated here.
        timeout = self.prepared_reset_timeout if method == 'tools/call' and params.get('name') == 'reset' else 60
        connection = http.client.HTTPConnection('browser', 8081, timeout=timeout)
        try:
            connection.request(
                'POST',
                '/mcp',
                body=data,
                headers={'Content-Type': 'application/json', 'Content-Length': str(len(data)), 'Connection': 'close'},
            )
            response = connection.getresponse()
            raw = response.read(8_000_001)
            if notification and response.status == 202 and not raw:
                return None
            if response.status != 200 or len(raw) > 8_000_000:
                raise RuntimeError('Broker response failed')
            result = strict_json(raw)
            if result.get('id') != self.sequence or 'error' in result:
                raise RuntimeError('Broker response failed')
            return result['result']
        finally:
            connection.close()


class Bridge:
    def __init__(self, workspace, output, audit, manifest, arm, platform, viewport, *, broker=None, profile='generic'):
        self.workspace, self.output, self.audit = Path(workspace), Path(output), Path(audit)
        self.manifest, self.arm, self.platform, self.viewport = manifest, arm, platform, tuple(viewport)
        self.tools = {t['name']: t for t in catalog(arm, platform, profile)}
        self.budget = codex_budget(arm, 3600)
        self.broker = broker
        self.lock = threading.Lock()
        self.count = self.sequence = self.bytes = 0
        self.session = uuid.uuid4().hex
        self.audit.mkdir(parents=True, exist_ok=True)
        (self.audit / 'images').mkdir(exist_ok=True)
        # A valid session may finish without invoking any tool. Establish its
        # empty ledger before readiness so audits can distinguish zero calls
        # from missing evidence. Never recreate or truncate an existing ledger.
        with (self.audit / 'bridge.ndjson').open('xb'):
            pass
        self.fatal = False

    def inputs(self, relative):
        if relative not in self.manifest['files']:
            raise ValueError('Path denied')
        data = read_regular(self.workspace, relative)
        if digest(data) != self.manifest['files'][relative]:
            raise RuntimeError('Public input integrity failure')
        return data

    def read(self, path):
        relative = virtual(path)
        if relative.startswith('output/'):
            return read_regular(self.output, relative[7:])
        return self.inputs(relative)

    def outputs(self):
        checked_path(self.output, 'placeholder', missing=True)
        files, directories = {}, 0
        for directory, dirs, names in os.walk(self.output, followlinks=False):
            for name in dirs:
                p = Path(directory) / name
                if not stat.S_ISDIR(p.lstat().st_mode):
                    raise ValueError('Output directory denied')
                directories += 1
            for name in names:
                relative = (Path(directory) / name).relative_to(self.output).as_posix()
                files[relative] = read_regular(self.output, relative, 65_536)
        return files, directories

    def write(self, args):
        relative = virtual(args['path'])
        if not relative.startswith('output/'):
            raise ValueError('Path denied')
        relative = relative[7:]
        parts = relative.split('/')
        if len(relative.encode()) > 192 or len(parts) > 4 or any(len(p.encode()) > 64 for p in parts):
            raise ValueError('Output path budget exceeded')
        data = args['content'].encode('utf-8')
        if len(data) > (16_384 if relative == 'judgment.json' else 65_536):
            raise ValueError('Output file budget exceeded')
        files, directories = self.outputs()
        old = files.get(relative)
        if 'expected_sha256' in args and (old is None or digest(old) != args['expected_sha256']):
            raise ValueError('Output hash conflict')
        if len(files) + (old is None) > 128 or sum(map(len, files.values())) - len(old or b'') + len(data) > 4_000_000:
            raise ValueError('Output budget exceeded')
        path = checked_path(self.output, relative, missing=True)
        needed = [p for p in path.parent.parents if p.is_relative_to(self.output) and not p.exists()]
        needed += [path.parent] if not path.parent.exists() else []
        if directories + len(set(needed)) > 64:
            raise ValueError('Output directory budget exceeded')
        path.parent.mkdir(parents=True, exist_ok=True)
        checked_path(self.output, relative, missing=True)
        fd, temp = tempfile.mkstemp(prefix='.atomic-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            checked_path(self.output, relative, missing=True)
            os.replace(temp, path)
        finally:
            Path(temp).unlink(missing_ok=True)
        return dict(
            path=args['path'],
            sha256=digest(data),
            bytes=len(data),
            previous_sha256=digest(old) if old is not None else None,
        )

    def operation(self, name, args):
        if name == 'bench_write_file':
            return self.text(self.write(args))
        if name == 'bench_list_files':
            entries = []
            outputs, _ = self.outputs()
            for relative, data in [(r, self.inputs(r)) for r in sorted(self.manifest['files'])] + [
                ('output/' + r, d) for r, d in sorted(outputs.items())
            ]:
                entries.append(
                    dict(
                        path='/workspace/' + relative,
                        bytes=len(data),
                        sha256=digest(data),
                        kind='image/png' if relative.endswith('.png') else 'text',
                    )
                )
            return self.text(entries)
        if name == 'bench_read_image':
            relative = virtual(args['path'])
            data = self.inputs(relative)
            from gui_agent_bench.visual import png_size

            if not relative.endswith('.png') or png_size(data) != self.viewport:
                raise ValueError('PNG dimensions differ')
            return {'content': observation_content(data, self.viewport, self.platform), 'isError': False}
        if name == 'bench_read_file':
            if args['path'].endswith('.png'):
                raise ValueError('Use bench_read_image')
            data = self.read(args['path'])
            data.decode('utf-8', 'strict')
            offset, size = args.get('offset', 0), args.get('max_bytes', 8192)
            if offset > len(data):
                raise ValueError('Invalid byte offset')
            data[:offset].decode('utf-8', 'strict')
            end = min(offset + size, len(data))
            while True:
                try:
                    page = data[offset:end].decode('utf-8', 'strict')
                    break
                except UnicodeDecodeError:
                    end -= 1
            return self.text(
                dict(
                    path=args['path'],
                    encoding='utf-8',
                    sha256=digest(data),
                    total_bytes=len(data),
                    offset=offset,
                    end_offset=end,
                    next_offset=end if end < len(data) else None,
                    eof=end == len(data),
                    text=page,
                )
            )
        if name.startswith('gui_') and self.broker:
            return self.broker.request('tools/call', {'name': name[4:], 'arguments': args})
        raise ValueError('Capability denied')

    @staticmethod
    def text(value):
        return {'content': [{'type': 'text', 'text': canonical(value).decode()}], 'isError': False}

    def record(self, value):
        self.sequence += 1
        value = dict(schema='codex-tool-v1', sequence=self.sequence, **value)
        data = canonical(value) + b'\n'
        if self.bytes + len(data) > self.budget['evidence_bytes']:
            self.fatal = True
            raise RuntimeError('Bridge evidence overflow')
        with (self.audit / 'bridge.ndjson').open('ab') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        self.bytes += len(data)

    def call(self, name, args, request_id):
        from jsonschema import Draft202012Validator

        with self.lock:
            self.count += 1
            call_id = f'{self.session}:{self.count}'
            common = dict(bridge_call_id=call_id, mcp_request_id=request_id, tool=name, arguments=args)
            self.record(dict(**common, phase='started'))
            denied, failed = False, False
            recovered = None
            try:
                if self.fatal:
                    from gui_agent_bench.failures import Failure

                    raise Failure(getattr(self, 'fatal_cause', 'unknown_operation_error'))
                if self.count > self.budget['bridge_calls']:
                    self.fatal = True
                    raise RuntimeError('Bridge budget exhausted')
                if name not in self.tools:
                    raise ValueError('Capability denied')
                errors = list(Draft202012Validator(self.tools[name]['inputSchema']).iter_errors(args))
                if errors:
                    if (
                        name == 'bench_read_file'
                        and isinstance(args, dict)
                        and any(list(error.path) == ['max_bytes'] for error in errors)
                    ):
                        raise ReadPageSizeError()
                    raise ValueError('Invalid arguments')
                result = self.operation(name, args)
                if (
                    sum(len(c['text'].encode()) for c in result['content'] if c['type'] == 'text') > 65_536
                    or len(canonical(result)) > 8_000_000
                ):
                    raise RuntimeError('Complete result exceeds budget')
                failed = bool(result.get('isError'))
                if failed:
                    from gui_agent_bench.authoring_recovery import recovery_from_result
                    from gui_agent_bench.failures import authoring_feedback, result_cause

                    recovered = recovery_from_result(result, self.platform, name)
                    if recovered and recovered['sequence'] == getattr(self, 'recoveries', 0) + 1:
                        self.recoveries = recovered['sequence']
                    elif authoring_feedback(result, name):
                        recovered = None
                    else:
                        recovered = None
                        self.fatal = True
                        self.fatal_cause = result_cause(result) or 'unknown_operation_error'
            except ReadPageSizeError:
                denied = True
                result = self.text(
                    {
                        'version': 'failure-v1',
                        'cause': 'invalid_arguments',
                        'message': 'max_bytes must be an integer from 4 through 8192. '
                        'Omit max_bytes to use 8192; follow next_offset until eof=true.',
                    }
                )
                result['isError'] = True
            except (ValueError, UnicodeError):
                # Failure is a ValueError subclass: preserve a latched trusted
                # cause instead of misreporting later calls as invalid arguments.
                if self.fatal:
                    from gui_agent_bench.failures import Failure, public_error

                    failed = True
                    result = self.text(public_error(Failure(getattr(self, 'fatal_cause', 'unknown_operation_error'))))
                    result['isError'] = True
                else:
                    denied = True
                    result = self.text(
                        {'version': 'failure-v1', 'cause': 'invalid_arguments', 'message': 'Operation denied.'}
                    )
                    result['isError'] = True
            except Exception:
                failed = self.fatal = True
                result = self.text(
                    {'version': 'failure-v1', 'cause': 'unknown_operation_error', 'message': 'Operation failed.'}
                )
                result['isError'] = True
            result['_meta'] = {META: call_id}
            stored = json.loads(json.dumps(result))
            for block in stored['content']:
                if block['type'] == 'image':
                    data = base64.b64decode(block.pop('data'), validate=True)
                    sha = digest(data)
                    blob = self.audit / 'images' / (sha + '.png')
                    if not blob.exists():
                        if self.bytes + len(data) > self.budget['evidence_bytes']:
                            raise RuntimeError('Bridge image overflow')
                        blob.write_bytes(data)
                        self.bytes += len(data)
                    block.update(sha256=sha, bytes=len(data), blob='images/' + sha + '.png')
            self.record(
                dict(
                    **common,
                    phase='completed',
                    result=stored,
                    denied=denied,
                    operation_failed=failed,
                    **({'recovery': recovered} if recovered else {}),
                )
            )
            return result


async def serve():
    import anyio
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server
    from mcp import types

    policy = strict_json(Path('/policy/bridge.json').read_bytes())
    profile = policy.get('environment_profile', 'generic')
    tools = catalog(policy['arm'], policy['platform'], profile)
    broker = (
        Broker(tools, arm=policy['arm'], platform=policy['platform'], profile=profile)
        if policy['arm'] != 'judge_visual'
        else None
    )
    bridge = Bridge(
        '/workspace',
        '/workspace/output',
        '/audit',
        policy['manifest'],
        policy['arm'],
        policy['platform'],
        policy['viewport'],
        broker=broker,
        profile=profile,
    )
    server = Server('bench')

    @server.list_tools()
    async def list_tools():
        return [types.Tool(**tool) for tool in tools]

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        request_id = server.request_context.request_id
        result = await anyio.to_thread.run_sync(bridge.call, name, arguments, request_id)
        return types.CallToolResult(**result)

    class Reader:
        def __init__(self, stream):
            self.stream, self.other = stream, 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            raw = await anyio.to_thread.run_sync(self.stream.wrapped.readline, 1_048_577)
            line = raw.decode('utf-8', 'strict')
            if not line:
                raise StopAsyncIteration
            if len(line.encode('utf-8')) > 1_048_576 or not line.endswith('\n'):
                raise ValueError('Invalid MCP frame')
            frame = strict_json(line.encode('utf-8'))
            if not isinstance(frame, dict) or frame.get('jsonrpc') != '2.0':
                raise ValueError('Invalid MCP envelope')
            if frame.get('method') != 'tools/call':
                self.other += 1
                if self.other > 4096:
                    raise ValueError('MCP protocol budget exceeded')
            return line

    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind('/ipc/bench.sock')
    os.chmod('/ipc/bench.sock', 0o600)
    listener.listen(1)
    connection, _ = await anyio.to_thread.run_sync(listener.accept)
    listener.close()  # exactly one session; never reconnect/replay
    with (
        connection,
        connection.makefile('rb') as reader,
        connection.makefile('w', encoding='utf-8', errors='strict', newline='\n') as writer,
    ):
        async with stdio_server(stdin=Reader(anyio.wrap_file(reader)), stdout=anyio.wrap_file(writer)) as (
            incoming,
            outgoing,
        ):
            await server.run(
                incoming, outgoing, server.create_initialization_options(), raise_exceptions=False, stateless=False
            )


if __name__ == '__main__':
    import anyio

    try:
        anyio.run(serve)
    except BaseException:
        # Never let SDK/OS exception detail reach the model or credential logs.
        raise SystemExit(1) from None
