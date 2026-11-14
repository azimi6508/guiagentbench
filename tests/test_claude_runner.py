import importlib.util
import http.client
import http.server
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from gui_agent_bench.failures import Failure
from gui_agent_bench.io import digest
from gui_agent_bench.runners.base import AuthoringContext
from gui_agent_bench.runners.claude import provider_failure_cause, provider_record_success, validate_provider
from gui_agent_bench.runners.claude_auth import credentials
from gui_agent_bench.runners.claude_config import budget, render
from gui_agent_bench.runners.claude_protocol import Session
from gui_agent_bench.runners.registry import resolve, effort

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('claude_gateway', ROOT / 'runtime/claude/gateway.py')
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)

TOOLS = ['mcp__bench__bench_list_files', 'mcp__bench__bench_write_file']
GATEWAY_ENV = {
    'GAB_CLAUDE_AUTH_KIND': 'api_key',
    'GAB_CLAUDE_CREDENTIAL': 'sk-real-test-value',
    'GAB_CLAUDE_MODEL': 'claude-test-5',
    'GAB_CLAUDE_EFFORT': 'medium',
    'GAB_CLAUDE_TOOLS': ','.join(TOOLS),
    'GAB_CLAUDE_REQUEST_LIMIT': '3',
}


def body(**changes):
    value = {
        'model': 'claude-test-5',
        'stream': True,
        'max_tokens': 32000,
        'messages': [{'role': 'user', 'content': 'x'}],
        'tools': [{'name': n, 'description': 'd', 'input_schema': {'type': 'object'}} for n in TOOLS],
        'output_config': {'effort': 'medium'},
        'context_management': {'edits': [{'type': 'clear_thinking_20251015', 'keep': 'all'}]},
    }
    value.update(changes)
    return json.dumps(value).encode()


def sse(*events):
    return b''.join(b'event: ' + e['type'].encode() + b'\ndata: ' + json.dumps(e).encode() + b'\n\n' for e in events)


SUCCESS = sse(
    {'type': 'message_start', 'message': {'model': 'claude-test-5', 'usage': {'input_tokens': 7, 'output_tokens': 1}}},
    {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {'output_tokens': 3}},
    {'type': 'message_stop'},
)


class ClaudeRegistryAndAuthTests(unittest.TestCase):
    def test_explicit_model_and_effort_are_required(self):
        agent = resolve('claude/claude-sonnet-5-5', reasoning_effort='high')
        self.assertEqual((agent.runner, agent.model, agent.reasoning_effort), ('claude', 'claude-sonnet-5-5', 'high'))
        for model in ('claude/opus', 'claude/default', 'claude/claude-x/y', 'claude/claude..x'):
            with self.assertRaises(ValueError):
                resolve(model)
        with self.assertRaises(ValueError):
            resolve('claude/claude-sonnet-5-5', reasoning_effort='extreme')
        self.assertEqual(effort('claude/claude-x', 'low', 'max'), 'max')
        self.assertEqual(effort('codex/gpt', 'low', 'max'), 'low')

    def test_exactly_one_credential_selects_billing(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-a'}, clear=True):
            self.assertEqual(credentials(), ('api_key', 'sk-a'))
        with patch.dict(os.environ, {'CLAUDE_CODE_OAUTH_TOKEN': 'sk-o'}, clear=True):
            self.assertEqual(credentials(), ('oauth', 'sk-o'))
        for environment in (
            {},
            {'ANTHROPIC_API_KEY': 'a', 'CLAUDE_CODE_OAUTH_TOKEN': 'b'},
            {'ANTHROPIC_API_KEY': 'has space'},
        ):
            with patch.dict(os.environ, environment, clear=True), self.assertRaises(ValueError):
                credentials()


class ClaudePolicyTests(unittest.TestCase):
    def context(self, folder, arm='judge_visual', platform='web'):
        (folder / 'workspace').mkdir()
        (folder / 'config').mkdir()
        text = b'Judge the screenshot.'
        (folder / 'workspace/instruction.md').write_bytes(text)
        manifest = {'arm': arm, 'platform': platform, 'files': {'instruction.md': digest(text)}}
        return AuthoringContext(
            't',
            arm,
            platform,
            (800, 600),
            folder / 'workspace',
            manifest,
            folder / 'output',
            folder / 'config',
            folder / 'logs/agent',
            'net',
            None,
            60,
        )

    def test_policy_admits_only_bench_tools_and_holds_no_credential(self):
        with tempfile.TemporaryDirectory() as raw, patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-secret-value'}):
            folder = Path(raw)
            context = self.context(folder)
            policy = render(folder / 'config', resolve('claude/claude-test-5'), context, 'api_key')
            self.assertTrue(all(n.startswith('mcp__bench__bench_') for n in policy['tool_names']))
            settings = json.loads((folder / 'config/settings.json').read_text())
            self.assertEqual(settings['permissions']['allow'], policy['tool_names'])
            self.assertEqual(settings['permissions']['defaultMode'], 'dontAsk')
            self.assertTrue(policy['instruction'].endswith('Judge the screenshot.'))
            for path in (folder / 'config').iterdir():
                self.assertNotIn('sk-secret-value', path.read_text())
            with self.assertRaises(ValueError):
                render(folder / 'config', resolve('claude/claude-test-5'), context, 'cookie')

    def test_gui_arms_add_gui_tools(self):
        with tempfile.TemporaryDirectory() as raw:
            policy = render(
                Path(raw) / 'config', resolve('claude/claude-test-5'), self.context(Path(raw), 'test_ui'), 'oauth'
            )
            self.assertIn('mcp__bench__gui_observe', policy['tool_names'])
            self.assertIn('mcp__bench__gui_dump_ui', policy['tool_names'])
            self.assertEqual(budget('test_ui', 600)['profile'], 'claude-bounded-v1')


class GatewayPolicyTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, GATEWAY_ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.state = gateway.State()
        self.headers = {'x-api-key': 'placeholder'}

    def reject(self, data=None, path='/v1/messages?beta=true', headers=None, method='POST'):
        return self.state.rejection(method, path, headers or self.headers, body() if data is None else data)

    def test_valid_request_is_admitted(self):
        self.assertIsNone(self.reject())

    def test_every_policy_deviation_is_rejected(self):
        cases = {
            'path': dict(path='/v1/complete'),
            'credential_shape': dict(headers={'authorization': 'Bearer x'}),
            'model': dict(data=body(model='claude-other')),
            'stream': dict(data=body(stream=False)),
            'request_field': dict(data=body(mcp_servers=[])),
            'context_edit': dict(data=body(context_management={'edits': [{'type': 'clear_tool_uses_20250919'}]})),
            'effort': dict(data=body(output_config={'effort': 'max'})),
            'request_json': dict(data=b'{"model": NaN}'),
        }
        for reason, arguments in cases.items():
            self.assertEqual(self.reject(**arguments), reason)
        extra = json.loads(body())
        extra['tools'].append({'name': 'Bash', 'input_schema': {}})
        self.assertEqual(self.reject(json.dumps(extra).encode()), 'tool')
        server = json.loads(body())
        server['tools'] = [{'type': 'web_search_20250305', 'name': 'web_search'}]
        self.assertEqual(self.reject(json.dumps(server).encode()), 'tool')

    def test_budget_and_failure_are_final(self):
        self.state.count = 3
        self.assertEqual(self.reject(), 'request_budget')
        self.state.count, self.state.failed = 0, True
        self.assertEqual(self.reject(), 'after_failure')


class Upstream(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    replies = []
    seen = []

    def log_message(self, *_):
        pass

    def do_POST(self):
        data = self.rfile.read(int(self.headers['content-length']))
        Upstream.seen.append((dict(self.headers), data))
        status, payload = Upstream.replies.pop(0)
        self.send_response(status)
        self.send_header('content-type', 'text/event-stream' if status == 200 else 'application/json')
        self.send_header('content-length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class GatewayRelayTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, GATEWAY_ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        Upstream.seen = []
        self.upstream = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        port = self.upstream.server_address[1]
        connection = patch.object(
            gateway, 'connection', lambda: http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        )
        connection.start()
        self.addCleanup(connection.stop)
        self.relay = gateway.GatewayHTTPServer(('127.0.0.1', 0), gateway.Handler)
        self.relay.state = gateway.State()
        threading.Thread(target=self.relay.serve_forever, daemon=True).start()
        self.rows = []
        recorder = patch.object(gateway, 'record', self.rows.append)
        recorder.start()
        self.addCleanup(recorder.stop)
        for server in (self.upstream, self.relay):
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)

    def post(self, data=None):
        recorded = len(self.rows)
        client = http.client.HTTPConnection('127.0.0.1', self.relay.server_address[1], timeout=10)
        client.request(
            'POST',
            '/v1/messages?beta=true',
            data or body(),
            {'x-api-key': 'placeholder', 'content-type': 'application/json', 'x-stainless-os': 'Linux'},
        )
        response = client.getresponse()
        try:
            return response.status, response.read()
        finally:
            client.close()
            # The relay records its row after it has answered; wait for it.
            deadline = time.monotonic() + 5
            while len(self.rows) == recorded and time.monotonic() < deadline:
                time.sleep(0.01)

    def test_credential_is_injected_and_usage_recorded(self):
        Upstream.replies = [(200, SUCCESS)]
        status, data = self.post()
        self.assertEqual((status, data), (200, SUCCESS))
        headers, forwarded = Upstream.seen[0]
        lower = {k.lower(): v for k, v in headers.items()}
        self.assertEqual(lower['x-api-key'], 'sk-real-test-value')
        self.assertNotIn('x-stainless-os', lower)
        self.assertEqual(forwarded, body())
        row = self.rows[0]
        self.assertTrue(provider_record_success(row))
        self.assertEqual(row['usage'], {'input_tokens': 7, 'output_tokens': 3})
        self.assertEqual(row['resolved_model'], 'claude-test-5')
        self.assertNotIn('sk-real-test-value', json.dumps(self.rows))
        self.assertEqual(validate_provider(self.rows), self.rows)
        self.assertEqual(row['effort'], 'medium')

    def test_request_without_effort_is_recorded_as_such(self):
        Upstream.replies = [(200, SUCCESS)]
        without = json.loads(body())
        del without['output_config']
        status, _ = self.post(json.dumps(without).encode())
        self.assertEqual(status, 200)
        self.assertIsNone(self.rows[0]['effort'])

    def test_upstream_failure_is_never_replayed(self):
        Upstream.replies = [
            (429, b'{"type":"error","error":{"type":"rate_limit_error","message":"m"}}'),
            (200, SUCCESS),
        ]
        self.assertEqual(self.post()[0], 429)
        self.assertEqual(self.post()[0], 403)
        self.assertEqual(len(Upstream.seen), 1)
        self.assertEqual([r['outcome'] for r in self.rows], ['upstream_status', 'rejected'])
        self.assertEqual(provider_failure_cause(self.rows[0]), 'provider_rate_limit')
        self.assertEqual(self.rows[1]['rejection_reason'], 'after_failure')
        with self.assertRaises(ValueError):
            validate_provider(self.rows)

    def test_overloaded_stream_error_is_a_provider_failure(self):
        Upstream.replies = [
            (
                200,
                sse(
                    {'type': 'message_start', 'message': {'model': 'claude-test-5'}},
                    {'type': 'error', 'error': {'type': 'overloaded_error'}},
                ),
            )
        ]
        self.post()
        self.assertEqual(self.rows[0]['outcome'], 'stream_error')
        self.assertEqual(provider_failure_cause(self.rows[0]), 'provider_capacity')


class CaptureSessionTests(unittest.TestCase):
    policy = {'model': 'claude-test-5', 'tool_names': TOOLS}
    limits = {'observed_tool_items': 4}

    def init(self, **changes):
        value = {
            'type': 'system',
            'subtype': 'init',
            'tools': TOOLS,
            'model': 'claude-test-5',
            'permissionMode': 'dontAsk',
            'mcp_servers': [{'name': 'bench', 'status': 'connected'}],
        }
        value.update(changes)
        return value

    def run_events(self, *events):
        session = Session(self.policy, self.limits)
        for event in events:
            session.event(event)
        return session

    def assertCause(self, cause, *events):
        with self.assertRaises(Failure) as error:
            self.run_events(*events)
        self.assertEqual(error.exception.cause, cause)

    def test_complete_session(self):
        session = self.run_events(
            self.init(),
            {
                'type': 'assistant',
                'message': {
                    'id': 'm1',
                    'model': 'claude-test-5',
                    'content': [
                        {'type': 'thinking', 'thinking': 'x'},
                        {'type': 'tool_use', 'id': 't1', 'name': TOOLS[0], 'input': {}},
                    ],
                },
            },
            {'type': 'rate_limit_event', 'rate_limit_info': {'status': 'allowed', 'isUsingOverage': False}},
            {
                'type': 'system',
                'subtype': 'thinking_tokens',
                'estimated_tokens': 50,
                'estimated_tokens_delta': 50,
                'session_id': 's',
                'uuid': 'u',
            },
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'content': []}]}},
            {
                'type': 'assistant',
                'message': {'id': 'm2', 'model': 'claude-test-5', 'content': [{'type': 'text', 'text': 'done'}]},
            },
            {
                'type': 'result',
                'subtype': 'success',
                'is_error': False,
                'terminal_reason': 'completed',
                'permission_denials': [],
            },
            {'type': 'bench_child_exit', 'exit_code': 0},
        )
        self.assertTrue(session.exited)
        self.assertEqual(len(session.calls), 1)

    def test_deviations_have_stable_causes(self):
        tool = lambda name: {
            'type': 'assistant',
            'message': {'model': 'm', 'content': [{'type': 'tool_use', 'id': 't', 'name': name, 'input': {}}]},
        }
        self.assertCause('capability_unavailable', self.init(tools=TOOLS + ['Bash']))
        self.assertCause('capability_unavailable', self.init(mcp_servers=[{'name': 'bench', 'status': 'failed'}]))
        self.assertCause('policy_violation', self.init(permissionMode='bypassPermissions'))
        self.assertCause('policy_violation', self.init(), tool('Bash'))
        self.assertCause(
            'provider_error', self.init(), {'type': 'assistant', 'message': {'model': '<synthetic>', 'content': []}}
        )
        self.assertCause('context_overflow', self.init(), {'type': 'system', 'subtype': 'compact_boundary'})
        self.assertCause('provider_transport_error', self.init(), {'type': 'system', 'subtype': 'api_retry'})
        self.assertCause(
            'incomplete_trajectory',
            self.init(),
            {'type': 'system', 'subtype': 'thinking_tokens', 'estimated_tokens': -1, 'estimated_tokens_delta': 0},
        )
        self.assertCause(
            'incomplete_trajectory',
            self.init(),
            {
                'type': 'system',
                'subtype': 'thinking_tokens',
                'estimated_tokens': 1,
                'estimated_tokens_delta': 1,
                'text': 'unexpected',
            },
        )
        self.assertCause(
            'incomplete_trajectory',
            {'type': 'system', 'subtype': 'thinking_tokens', 'estimated_tokens': 1, 'estimated_tokens_delta': 1},
        )
        self.assertCause(
            'budget_exhausted',
            self.init(),
            {'type': 'rate_limit_event', 'rate_limit_info': {'status': 'allowed', 'isUsingOverage': True}},
        )
        self.assertCause(
            'provider_rate_limit', self.init(), {'type': 'rate_limit_event', 'rate_limit_info': {'status': 'rejected'}}
        )
        self.assertCause(
            'incomplete_trajectory',
            self.init(),
            {'type': 'result', 'subtype': 'success', 'is_error': True, 'terminal_reason': 'api_error'},
        )
        self.assertCause(
            'incomplete_trajectory',
            self.init(),
            tool(TOOLS[0]),
            {'type': 'result', 'subtype': 'success', 'is_error': False},
        )
        self.assertCause('incomplete_trajectory', {'type': 'assistant', 'message': {'content': []}})


if __name__ == '__main__':
    unittest.main()
