"""Per-trial Anthropic Messages relay for the Claude Code runner.

The agent container only holds a placeholder credential and reaches this relay
on an internal network. The relay admits only streamed POST /v1/messages for
the single selected model and effort, with exactly the trial's bench MCP tools
and no context edits beyond keeping all thinking. It replaces the placeholder
with the real credential, forwards the body byte-for-byte and records one
content-free audit row per request on stdout. Any rejection or upstream
failure is final for the trial: later requests are refused, so neither the
client nor the relay can replay a request.
"""

import hashlib
import http.client
import http.server
import json
import os
import sys
import threading
import time

UPSTREAM = ('api.anthropic.com', 443)
PATHS = {'/v1/messages', '/v1/messages?beta=true'}
FORWARD_HEADERS = {'content-type', 'accept', 'anthropic-version', 'anthropic-beta', 'user-agent', 'x-app'}
FIELDS = {
    'model',
    'messages',
    'system',
    'tools',
    'tool_choice',
    'max_tokens',
    'stream',
    'metadata',
    'thinking',
    'output_config',
    'context_management',
    'temperature',
    'stop_sequences',
    'top_p',
    'top_k',
}
TOOL_FIELDS = {'name', 'description', 'input_schema', 'cache_control', 'strict'}
KEEP_THINKING = {'type': 'clear_thinking_20251015', 'keep': 'all'}
REQUEST_BYTES = 32_000_000
RESPONSE_BYTES = 16_000_000
EVENT_BYTES = 8_000_000
LOCK = threading.Lock()


def connection():
    return http.client.HTTPSConnection(*UPSTREAM, timeout=600)


def record(row):
    sys.stdout.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n')
    sys.stdout.flush()


def strict(data):
    def reject(value):
        raise ValueError('Non-finite JSON number')

    return json.loads(data, parse_constant=reject)


def error_body(kind):
    return json.dumps({'type': 'error', 'error': {'type': kind, 'message': 'Benchmark gateway policy.'}}).encode()


class Stream:
    """Incremental server-sent-event reader that keeps only usage metadata."""

    def __init__(self):
        self.buffer = b''
        self.model = None
        self.usage = {}
        self.stop_reason = None
        self.stopped = False
        self.error = None

    def feed(self, chunk):
        self.buffer += chunk.replace(b'\r\n', b'\n')
        if len(self.buffer) > EVENT_BYTES:
            raise ValueError('event_bytes')
        while b'\n\n' in self.buffer:
            block, self.buffer = self.buffer.split(b'\n\n', 1)
            data = b'\n'.join(line[5:].lstrip() for line in block.split(b'\n') if line.startswith(b'data:'))
            if data:
                self.event(strict(data))

    def event(self, value):
        kind = value.get('type') if isinstance(value, dict) else None
        if kind == 'message_start':
            message = value.get('message') or {}
            self.model = message.get('model')
            self.usage.update(numbers(message.get('usage')))
        elif kind == 'message_delta':
            self.usage.update(numbers(value.get('usage')))
            self.stop_reason = (value.get('delta') or {}).get('stop_reason')
        elif kind == 'message_stop':
            self.stopped = True
        elif kind == 'error':
            self.error = str((value.get('error') or {}).get('type') or 'unknown')[:64]


def numbers(usage):
    if not isinstance(usage, dict):
        return {}
    return {k: v for k, v in usage.items() if type(v) is int and v >= 0}


class State:
    def __init__(self):
        self.kind = os.environ['GAB_CLAUDE_AUTH_KIND']
        if self.kind not in {'api_key', 'oauth'} or not os.environ.get('GAB_CLAUDE_CREDENTIAL'):
            raise ValueError('Gateway credential unavailable')
        self.model = os.environ['GAB_CLAUDE_MODEL']
        self.effort = os.environ['GAB_CLAUDE_EFFORT']
        self.tools = {name for name in os.environ['GAB_CLAUDE_TOOLS'].split(',') if name}
        self.limit = int(os.environ['GAB_CLAUDE_REQUEST_LIMIT'])
        self.identity = os.environ.get('GAB_CLAUDE_MODEL_IDENTITY') or None
        self.count = 0
        self.failed = False
        self.resolved = None

    def credential(self):
        secret = os.environ['GAB_CLAUDE_CREDENTIAL']
        return {'x-api-key': secret} if self.kind == 'api_key' else {'authorization': 'Bearer ' + secret}

    def rejection(self, method, path, headers, data):
        if self.failed:
            return 'after_failure'
        if method != 'POST' or path not in PATHS:
            return 'path'
        api_key, bearer = headers.get('x-api-key'), headers.get('authorization')
        if (self.kind == 'api_key' and (not api_key or bearer)) or (
            self.kind == 'oauth' and (api_key or not str(bearer or '').startswith('Bearer '))
        ):
            return 'credential_shape'
        if data is None or len(data) > REQUEST_BYTES:
            return 'request_bytes'
        try:
            body = strict(data)
        except ValueError:
            return 'request_json'
        if not isinstance(body, dict) or set(body) - FIELDS:
            return 'request_field'
        if body.get('model') != self.model:
            return 'model'
        if body.get('stream') is not True:
            return 'stream'
        tools = body.get('tools', [])
        if (
            not isinstance(tools, list)
            or any(not isinstance(t, dict) or set(t) - TOOL_FIELDS for t in tools)
            or not {t.get('name') for t in tools} <= self.tools
        ):
            return 'tool'
        context = body.get('context_management')
        if context is not None and (
            not isinstance(context, dict)
            or set(context) != {'edits'}
            or any(edit != KEEP_THINKING for edit in context['edits'])
        ):
            return 'context_edit'
        output = body.get('output_config')
        if output is not None and output != {'effort': self.effort}:
            return 'effort'
        if self.count >= self.limit:
            return 'request_budget'
        return None


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'bench-gateway'
    sys_version = ''

    def log_message(self, *_):
        pass

    def deny(self, row, reason, status=403, kind='permission_error'):
        self.server.state.failed = True
        body = error_body(kind)
        row.update(outcome='rejected', status=status, rejection_reason=reason)
        self.send_response(status)
        self.send_header('content-type', 'application/json')
        self.send_header('content-length', str(len(body)))
        self.send_header('connection', 'close')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def handle_any(self):
        state = self.server.state
        with LOCK:
            started = time.monotonic()
            headers = {k.lower(): v for k, v in self.headers.items()}
            data = None
            row = {'event': 'request', 'method': self.command, 'path': self.path if self.path in PATHS else 'other'}
            try:
                length = int(headers.get('content-length', '0'))
                if 0 <= length <= REQUEST_BYTES:
                    data = self.rfile.read(length)
                    row.update(request_bytes=len(data), request_sha256=hashlib.sha256(data).hexdigest())
            except ValueError:
                data = None
            reason = state.rejection(self.command, self.path, headers, data)
            if reason:
                self.deny(
                    row,
                    reason,
                    429 if reason == 'request_budget' else 403,
                    'rate_limit_error' if reason == 'request_budget' else 'permission_error',
                )
                row['elapsed_ms'] = int((time.monotonic() - started) * 1000)
                record(row)
                return
            state.count += 1
            row['sequence'] = state.count
            # Whether the client attached the selected effort to this request. A
            # model without an effort control receives none; the record keeps
            # that visible instead of implying the label was applied.
            try:
                row['effort'] = (json.loads(data).get('output_config') or {}).get('effort')
            except (ValueError, AttributeError, TypeError):
                row['effort'] = None
            self.relay(state, headers, data, row, started)
            record(row)

    def relay(self, state, headers, data, row, started):
        forward = {k: v for k, v in headers.items() if k in FORWARD_HEADERS}
        forward.update(state.credential())
        forward.update({'accept-encoding': 'identity', 'content-length': str(len(data))})
        stream = Stream()
        digest = hashlib.sha256()
        total = 0
        sent = False
        try:
            upstream = connection()
            upstream.request('POST', self.path, data, forward)
            response = upstream.getresponse()
            row['status'] = response.status
            row['upstream_request_id'] = (response.getheader('request-id') or '')[:128] or None
            self.send_response(response.status)
            for name in ('content-type', 'request-id'):
                if response.getheader(name):
                    self.send_header(name, response.getheader(name))
            self.send_header('connection', 'close')
            self.end_headers()
            sent = True
            failure = None
            body = b''
            while True:
                chunk = response.read1(65536)
                if not chunk:
                    break
                total += len(chunk)
                digest.update(chunk)
                if total > RESPONSE_BYTES:
                    failure = 'response_bytes'
                    break
                if response.status == 200:
                    stream.feed(chunk)
                elif len(body) < 65536:
                    body += chunk
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    failure = 'client_closed'
                    break
            upstream.close()
            if response.status != 200:
                failure = 'upstream_status'
                try:
                    row['error_type'] = str(strict(body)['error']['type'])[:64]
                except (ValueError, KeyError, TypeError):
                    row['error_type'] = None
            elif failure is None and stream.error:
                failure = 'stream_error'
                row['error_type'] = stream.error
            elif failure is None and not stream.stopped:
                failure = 'incomplete_stream'
            if failure is None and stream.model:
                if state.resolved is None:
                    state.resolved = stream.model
                if stream.model != state.resolved:
                    failure = 'model_changed'
                elif state.identity and stream.model != state.identity:
                    failure = 'model_identity'
            if failure is None and not stream.model:
                failure = 'model_identity'
            row.update(outcome='completed' if failure is None else failure)
        except (OSError, http.client.HTTPException, ValueError) as exc:
            row.update(outcome='transport_error', exception_kind=type(exc).__name__)
            if not sent:
                body = error_body('api_error')
                try:
                    self.send_response(502)
                    self.send_header('content-type', 'application/json')
                    self.send_header('content-length', str(len(body)))
                    self.send_header('connection', 'close')
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass
        if row['outcome'] != 'completed':
            state.failed = True
        row.update(
            response_bytes=total,
            response_sha256=digest.hexdigest(),
            resolved_model=stream.model,
            usage=stream.usage or None,
            stop_reason=stream.stop_reason,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        self.close_connection = True

    do_POST = do_GET = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = handle_any


class GatewayHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True


def identity_probe():
    """Resolve the selected model's catalog record; starts no inference."""
    state = State()
    upstream = connection()
    headers = {'anthropic-version': '2023-06-01', **state.credential()}
    if state.kind == 'oauth':
        headers['anthropic-beta'] = 'oauth-2025-04-20'
    upstream.request('GET', '/v1/models/' + state.model, headers=headers)
    response = upstream.getresponse()
    body = response.read(65537)
    row = {'event': 'model_identity', 'status': response.status}
    if response.status == 200 and len(body) <= 65536:
        value = strict(body)
        identity = {k: value.get(k) for k in ('id', 'type', 'display_name', 'created_at')}
        canonical = json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()
        row.update(identity, sha256=hashlib.sha256(canonical).hexdigest(), schema='anthropic-model-v1')
    record(row)
    return 0 if 'sha256' in row else 1


def main():
    if os.environ.get('GAB_CLAUDE_IDENTITY_PROBE') == '1':
        return identity_probe()
    server = GatewayHTTPServer(('0.0.0.0', 8080), Handler)
    server.state = State()
    server.serve_forever()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        record({'event': 'gateway_failure', 'exception_kind': type(exc).__name__})
        sys.exit(1)
