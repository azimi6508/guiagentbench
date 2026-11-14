"""One-endpoint inference relay; the isolated agent has no general internet route."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import time
import urllib.error
import urllib.request
import http.client
from gui_agent_bench.arms import generated, artifact_name
from gui_agent_bench.budgets import provider_requests, PROVIDER_REQUEST_BYTES
from gui_agent_bench.failures import Failure, issue, provider_cause, MESSAGES
from gui_agent_bench.inference_diagnostics import (
    VERSION as INFERENCE_VERSION,
    RESPONSE_LIMIT,
    status_code,
    request_summary,
    http_error_summary,
    inspect_response,
    usage_summary,
    credential_echo,
    transport_reason,
)


def adapt_final_step(payload: dict) -> bool:
    """Send OpenCode's exact max-steps notice as a user turn with tools disabled.

    The pinned client appends it as a trailing assistant (prefill) message while
    still advertising tools; Gemini via OpenRouter rejects that with HTTP 400.
    Only the byte-exact pinned notice is changed, never model-written content.
    """
    from gui_agent_bench.runners.opencode import MAX_STEPS_NOTICE

    messages = payload['messages']
    last = messages[-1] if messages else None
    if not (isinstance(last, dict) and last.get('role') == 'assistant'):
        return False
    content = last.get('content')
    if (
        isinstance(content, list)
        and len(content) == 1
        and isinstance(content[0], dict)
        and (content[0].get('type') == 'text')
    ):
        content = content[0].get('text')
    if content != MAX_STEPS_NOTICE or set(last) - {'role', 'content'}:
        return False
    messages[-1] = {'role': 'user', 'content': MAX_STEPS_NOTICE}
    if payload.get('tools'):
        payload['tool_choice'] = 'none'
    return True


class RelayFailure(Failure):
    """Trusted stage/reason, not the text of an upstream or socket exception."""

    def __init__(self, stage, reason, cause='provider_error', details=None):
        super().__init__(cause)
        self.stage, self.reason, self.details = (stage, reason, details or {})


def fixture_reply(
    messages: list, verdict: str, probe: bool, arm='judge_visual', oracle_control='pass', platform='web'
) -> tuple[dict, str]:
    """Scripted protocol fixture only. It never receives the trial's private label."""
    actions = []
    if probe:
        actions += [
            ('read', {'filePath': '/fixture-control.json'}),
            ('read', {'filePath': '/control.json'}),
            ('read', {'filePath': '/private/labels.json'}),
            ('read', {'filePath': '/config/opencode.json'}),
            ('bash', {'command': 'env', 'description': 'Isolation probe'}),
            ('write', {'filePath': '/workspace/escape.txt', 'content': 'probe'}),
            ('write', {'filePath': '/workspace/output/../escape.txt', 'content': 'probe'}),
        ]
    if generated(arm):
        from gui_agent_bench.reference_controls import CONTROLS as reference_controls

        if arm.startswith('test_'):
            from gui_agent_bench.test_fixtures import source
        else:
            from gui_agent_bench.oracle_fixtures import source
        actions += [('read', {'filePath': '/workspace/instruction.md'})]
        if arm.startswith('oracle_'):
            actions.append(('read', {'filePath': '/workspace/steps.json'}))
        if probe and platform == 'tv':
            actions += [('gui_step', {'action': 'press', 'key': 'up'}), ('gui_reset', {})]
        if probe:
            actions += [
                ('gui_open_url', {'url': 'http://app:8000/'}),
                ('gui_step', {'action': 'reload'}),
                ('gui_reset', {}),
            ]
        actions.append(('gui_observe', {}))
        if arm.endswith('_ui'):
            actions.append(('gui_dump_ui', {}))
        if probe and platform == 'tv':
            actions += [
                ('gui_step', {'action': 'evaluate', 'code': '1+1'}),
                ('gui_step', {'action': 'press', 'key': 'up', 'state': 39}),
            ]
        elif probe:
            actions += [
                ('gui_open_url', {'url': 'http://provider:8080/health'}),
                ('gui_step', {'action': 'evaluate', 'code': '1+1'}),
            ]
        if oracle_control in reference_controls and reference_controls[oracle_control].record.get('capture_ui'):
            from gui_agent_bench.visual_fixtures import author_actions

            actions += author_actions(oracle_control, arm.startswith('test_'))
        elif arm.endswith('_visual'):
            from gui_agent_bench.visual_fixtures import author_actions

            actions += author_actions(oracle_control, arm.startswith('test_'))
        code = source(oracle_control, arm)
        if code is not None:
            actions.append(('write', {'filePath': '/workspace/output/' + artifact_name(arm), 'content': code}))
    elif arm == 'judge_test':
        if platform == 'tv':
            actions += [
                ('read', {'filePath': '/workspace/test_source.py'}),
                ('gui_reset', {}),
                ('gui_step', {'action': 'press', 'key': 'up'}),
                ('gui_observe', {}),
            ]
        else:
            actions += [
                ('read', {'filePath': '/workspace/test_source.py'}),
                ('gui_reset', {}),
                ('gui_open_url', {'url': 'http://app:8000/'}),
                ('gui_step', {'action': 'reload'}),
                ('gui_dump_ui', {}),
                ('gui_observe', {}),
            ]
        if probe and platform == 'tv':
            actions += [
                ('gui_step', {'action': 'evaluate', 'code': '1+1'}),
                ('gui_step', {'action': 'press', 'key': 'up', 'state': 39}),
            ]
        elif probe:
            actions += [
                ('gui_open_url', {'url': 'http://provider:8080/health'}),
                ('gui_step', {'action': 'evaluate', 'code': '1+1'}),
            ]
    else:
        actions += [
            ('read', {'filePath': path})
            for path in (
                '/workspace/instruction.md',
                '/workspace/evidence/manifest.json',
                '/workspace/evidence/screenshots/0001.png',
                '/workspace/evidence/screenshots/0002.png',
                '/workspace/evidence/screenshots/0003.png',
            )
        ]
    if not generated(arm) and verdict != 'MISSING':
        actions.append(
            (
                'write',
                {
                    'filePath': '/workspace/output/judgment.json',
                    'content': json.dumps(
                        {'verdict': verdict, 'reason': 'Scripted transport fixture; not model reasoning.'}
                    ),
                },
            )
        )
    index = sum((len(message.get('tool_calls', [])) for message in messages if message.get('role') == 'assistant'))
    if index >= len(actions):
        return ({'role': 'assistant', 'content': 'Scripted response complete.'}, 'stop')
    name, arguments = actions[index]
    return (
        {
            'role': 'assistant',
            'content': None,
            'tool_calls': [
                {
                    'id': f'fixture_{index}',
                    'type': 'function',
                    'function': {'name': name, 'arguments': json.dumps(arguments)},
                }
            ],
        },
        'tool_calls',
    )


def serve(
    provider: str,
    model: str,
    verdict: str = 'PASS',
    probe: bool = False,
    arm='judge_visual',
    oracle_control='pass',
    platform='web',
    reasoning_effort=None,
):
    if provider not in ('fixture', 'openrouter'):
        raise ValueError('unsupported provider')
    from gui_agent_bench.runners.registry import OPENCODE_VARIANTS

    if reasoning_effort is not None and reasoning_effort not in OPENCODE_VARIANTS:
        raise ValueError('unsupported reasoning effort')
    secret = os.environ.get('OPENROUTER_API_KEY', '')
    if provider == 'openrouter' and (not secret):
        raise ValueError('OPENROUTER_API_KEY must be supplied via environment')

    class Handler(BaseHTTPRequestHandler):
        calls = 0

        def log_message(self, *_):
            pass

        def fail(self, status, message, cause='provider_error'):
            failure = issue(Failure(cause), phase='inference', operation='provider_request', impact='feedback')
            if hasattr(self, 'inference'):
                failure['inference'] = self.inference_record()
            elif provider == 'openrouter':
                failure['inference'] = {
                    'version': INFERENCE_VERSION,
                    'provider': 'openrouter',
                    'request': self.calls,
                    'stage': 'relay_request',
                    'reason': 'request_rejected',
                    'upstream_request_sent': False,
                    'relay_status': status,
                }
            print(json.dumps({'request': self.calls, 'failure': failure}), flush=True)
            if getattr(self, 'stream_started', False):
                self.close_connection = True
                if self.response_format == 'sse':
                    data = {
                        'error': {'code': 502, 'message': MESSAGES[cause]},
                        'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'error'}],
                    }
                    try:
                        self.wfile.write(b'data: ' + json.dumps(data).encode() + b'\n\n')
                        self.wfile.flush()
                    except OSError:
                        pass
                return
            message = MESSAGES[cause]
            data = json.dumps({'error': {'message': message}}).encode()
            try:
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except OSError:
                pass

        def inference_record(self):
            return {
                **self.inference,
                'elapsed_ms': round((time.monotonic() - self.started) * 1000),
                'stream_started': self.stream_started,
            }

        def write_response(self, data):
            try:
                self.wfile.write(data)
                self.wfile.flush()
            except OSError:
                raise RelayFailure('downstream_write', 'client_connection_failed', 'provider_transport_error') from None

        def begin_response(self, format):
            self.response_format = format
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream' if format == 'sse' else 'application/json')
                self.end_headers()
            except OSError:
                raise RelayFailure('downstream_write', 'client_connection_failed', 'provider_transport_error') from None
            self.stream_started = True

        def inspect_item(self, value, stage):
            error, reasons = inspect_response(value)
            if error is None and credential_echo(value, secret):
                raise RelayFailure('response_protocol', 'credential_echo')
            self.inference['finish_reasons'] = sorted(set(self.inference['finish_reasons']) | set(reasons))
            usage = usage_summary(value)
            if usage is not None:
                print(json.dumps({'request': self.calls, 'usage': usage}), flush=True)
            if error is not None:
                cause = 'provider_rate_limit' if error['error_code'] == 429 else 'provider_error'
                raise RelayFailure(stage, 'provider_error_response', cause, error)

        def relay(self, response):
            self.inference['upstream_status'] = status_code(response.status)
            content_type = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
            if content_type == 'application/json':
                self.inference['stage'] = 'upstream_read'
                data = response.read(RESPONSE_LIMIT + 1)
                self.inference['response_bytes'] = len(data)
                if len(data) > RESPONSE_LIMIT:
                    raise RelayFailure('response_protocol', 'response_limit', 'evidence_overflow')
                self.inference['stage'] = 'response_protocol'
                self.inspect_item(json.loads(data), 'upstream_json')
                self.begin_response('json')
                self.write_response(data)
                self.inference['completion_seen'] = True
            elif content_type == 'text/event-stream':
                self.begin_response('sse')
                raw, fields, event_error = ([], [], False)
                while True:
                    self.inference['stage'] = 'upstream_read'
                    remaining = RESPONSE_LIMIT - self.inference['response_bytes']
                    line = response.readline(remaining + 1)
                    self.inference['response_bytes'] += len(line)
                    if self.inference['response_bytes'] > RESPONSE_LIMIT:
                        raise RelayFailure('response_protocol', 'response_limit', 'evidence_overflow')
                    if not line:
                        raise RelayFailure('response_protocol', 'incomplete_stream')
                    raw.append(line)
                    if secret.encode() in line:
                        if not line.startswith(b'data:'):
                            raise RelayFailure('response_protocol', 'credential_echo')
                    field = line.rstrip(b'\r\n')
                    if field:
                        name, _, data = field.partition(b':')
                        data = data[1:] if data.startswith(b' ') else data
                        if name == b'data':
                            fields.append(data)
                        elif name == b'event' and data == b'error':
                            event_error = True
                        continue
                    self.inference['stage'] = 'response_protocol'
                    data = b'\n'.join(fields)
                    if event_error:
                        try:
                            self.inspect_item(json.loads(data), 'upstream_stream')
                        except (ValueError, TypeError) as exc:
                            if isinstance(exc, RelayFailure):
                                raise
                        raise RelayFailure('upstream_stream', 'provider_error_response')
                    if data == b'[DONE]':
                        self.write_response(b''.join(raw))
                        self.inference['completion_seen'] = True
                        break
                    if fields:
                        self.inspect_item(json.loads(data), 'upstream_stream')
                    self.write_response(b''.join(raw))
                    raw, fields, event_error = ([], [], False)
            else:
                raise RelayFailure('response_protocol', 'unsupported_content_type')
            self.inference.update(stage='complete', reason='complete')
            print(
                json.dumps(
                    {'request': self.calls, 'event': 'inference_complete', 'inference': self.inference_record()}
                ),
                flush=True,
            )

        def do_GET(self):
            if self.path == '/health':
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'OK')
            else:
                self.fail(404, 'endpoint not allowed')

        def do_POST(self):
            self.stream_started = False
            if self.path != '/v1/chat/completions':
                return self.fail(403, 'endpoint not allowed', 'policy_violation')
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= PROVIDER_REQUEST_BYTES:
                    return self.fail(413, 'complete request exceeds evidence budget', 'evidence_overflow')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    return self.fail(400, 'invalid request envelope', 'invalid_arguments')
                if payload.get('model') != model:
                    return self.fail(403, 'model not allowed', 'policy_violation')
                if not isinstance(payload.get('messages'), list):
                    return self.fail(400, 'messages required', 'invalid_arguments')
                if payload.get('tools') is not None and (not isinstance(payload['tools'], list)):
                    return self.fail(400, 'invalid tools envelope', 'invalid_arguments')
                if payload.get('tools'):
                    if not all(
                        (
                            isinstance(item, dict)
                            and isinstance(item.get('function'), dict)
                            and isinstance(item['function'].get('name'), str)
                            for item in payload['tools']
                        )
                    ):
                        return self.fail(400, 'invalid tools envelope', 'invalid_arguments')
                    advertised = {item['function']['name'] for item in payload['tools']}
                    gui_tools = {name for name in advertised if name.startswith('gui_')}
                    expected = (
                        {'gui_observe', 'gui_reset', 'gui_step', 'gui_open_url'} if arm != 'judge_visual' else set()
                    )
                    if arm == 'judge_test' or arm.endswith('_ui'):
                        expected.add('gui_dump_ui')
                    if platform == 'tv':
                        expected -= {'gui_dump_ui', 'gui_open_url'}
                    if gui_tools != expected:
                        known = {'gui_observe', 'gui_reset', 'gui_step', 'gui_open_url', 'gui_dump_ui'}
                        print(
                            json.dumps(
                                {
                                    'capability_error': True,
                                    'advertised_gui_tools': sorted(gui_tools & known),
                                    'unexpected_gui_tool_count': len(gui_tools - known),
                                }
                            ),
                            flush=True,
                        )
                        return self.fail(
                            400, 'required browser capability set is unavailable', 'capability_unavailable'
                        )
                    print(json.dumps({'capabilities_verified': True, 'gui_tools': sorted(gui_tools)}), flush=True)
                    # Every agent turn (a request offering tools) must carry the selected variant.
                    # The client's separate title request keeps its own setting.
                    if reasoning_effort is not None:
                        if payload.get('reasoning_effort') != reasoning_effort:
                            print(json.dumps({'capability_error': True, 'reasoning_effort_applied': False}), flush=True)
                            return self.fail(400, 'selected model variant was not applied', 'capability_unavailable')
                        print(json.dumps({'variant_verified': True, 'reasoning_effort': reasoning_effort}), flush=True)
                type(self).calls += 1
                if self.calls > provider_requests(arm):
                    return self.fail(429, 'trial request budget exhausted', 'budget_exhausted')
                if provider == 'fixture':
                    return self.fixture(payload)
                payload['max_tokens'] = 4096
                payload['transforms'] = []
                payload.pop('debug', None)
                adapted = adapt_final_step(payload)
                self.started = time.monotonic()
                self.inference = {
                    'version': INFERENCE_VERSION,
                    'provider': 'openrouter',
                    'request': self.calls,
                    'upstream_request_sent': False,
                    **request_summary(payload, length),
                    **({'client_adaptation': 'final_step_notice'} if adapted else {}),
                    'stage': 'upstream_connect',
                    'response_bytes': 0,
                    'completion_seen': False,
                    'finish_reasons': [],
                }
                print(
                    json.dumps(
                        {'request': self.calls, 'event': 'inference_request', 'inference': self.inference_record()}
                    ),
                    flush=True,
                )
                request = urllib.request.Request(
                    'https://openrouter.ai/api/v1/chat/completions',
                    data=json.dumps(payload).encode(),
                    headers={'Authorization': 'Bearer ' + secret, 'Content-Type': 'application/json'},
                    method='POST',
                )
                self.inference['upstream_request_sent'] = True
                with urllib.request.urlopen(request, timeout=90) as response:
                    self.relay(response)
            except urllib.error.HTTPError as exc:
                self.inference.update(
                    stage='upstream_http',
                    reason='http_error',
                    upstream_status=status_code(exc.code),
                    **http_error_summary(exc),
                )
                self.fail(exc.code, 'provider HTTP failure', provider_cause(exc))
            except RelayFailure as exc:
                self.inference.update(stage=exc.stage, reason=exc.reason, **exc.details)
                self.fail(502, 'provider relay failure', exc.cause)
            except Failure as exc:
                self.fail(502, 'provider relay failure', exc.cause)
            except (ValueError, OSError, KeyError, TypeError, RecursionError, http.client.HTTPException) as exc:
                if hasattr(self, 'inference'):
                    kind = provider_cause(exc)
                    self.inference['reason'] = (
                        transport_reason(exc)
                        if isinstance(exc, (OSError, http.client.HTTPException))
                        else 'invalid_response'
                    )
                    if isinstance(exc, http.client.HTTPException):
                        kind = 'provider_transport_error'
                else:
                    kind = provider_cause(exc)
                self.fail(502, 'provider protocol or transport failed', kind)
            except Exception:
                if hasattr(self, 'inference'):
                    self.inference['reason'] = 'unclassified_relay_error'
                self.fail(502, 'unclassified relay error')

        def fixture(self, payload):
            if payload.get('tools'):
                from gui_agent_bench.visual_fixtures import response_delay

                time.sleep(response_delay(payload['messages'], oracle_control, arm))
                message, reason = fixture_reply(payload['messages'], verdict, probe, arm, oracle_control, platform)
            else:
                message, reason = ({'role': 'assistant', 'content': 'GUI smoke'}, 'stop')
            identity = {'id': f'fixture-{self.calls}', 'created': int(time.time()), 'model': model}
            if payload.get('stream'):
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                delta = dict(message)
                if 'tool_calls' in delta:
                    delta['tool_calls'] = [{'index': index, **call} for index, call in enumerate(delta['tool_calls'])]
                for chunk in (
                    {
                        **identity,
                        'object': 'chat.completion.chunk',
                        'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}],
                    },
                    {
                        **identity,
                        'object': 'chat.completion.chunk',
                        'choices': [{'index': 0, 'delta': {}, 'finish_reason': reason}],
                        'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150},
                    },
                ):
                    self.wfile.write(b'data: ' + json.dumps(chunk).encode() + b'\n\n')
                self.wfile.write(b'data: [DONE]\n\n')
            else:
                data = json.dumps(
                    {
                        **identity,
                        'object': 'chat.completion',
                        'choices': [{'index': 0, 'message': message, 'finish_reason': reason}],
                        'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150},
                    }
                ).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

    HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
