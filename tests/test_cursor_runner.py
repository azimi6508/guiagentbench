import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gui_agent_bench.runners.registry import resolve
from gui_agent_bench.runners.cursor_auth import credentials
from gui_agent_bench.runners.cursor_config import budget, render
from gui_agent_bench.runners.cursor_protocol import capture
from gui_agent_bench.runners.base import AuthoringContext
from gui_agent_bench.io import digest
from gui_agent_bench.failures import Failure
from gui_agent_bench.runners.cursor import provider_failure_cause, provider_record_success

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cursor_gateway', ROOT / 'runtime/cursor/gateway.py')
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


def field(number, data):
    def integer(n):
        out = bytearray()
        while n > 127:
            out.append((n & 127) | 128)
            n >>= 7
        out.append(n)
        return bytes(out)

    return integer(number * 8 + 2) + integer(len(data)) + data


class CursorRunnerTests(unittest.TestCase):
    def test_protocol_traffic_does_not_consume_payload_allowance(self):
        state = gateway.State()
        with patch.dict(
            os.environ,
            {'GAB_CURSOR_PAYLOAD_LIMIT': '2', 'GAB_CURSOR_HEARTBEAT_LIMIT': '400', 'GAB_CURSOR_METADATA_LIMIT': '400'},
        ):
            for i in range(300):
                state.admit('/aiserver.v1.BidiService/BidiAppend', str(i).encode(), None, 'heartbeat', False)
                state.admit('/aiserver.v1.DashboardService/GetUserPrivacyMode', b'', None, 'metadata', False)
            state.admit('/aiserver.v1.BidiService/BidiAppend', b'payload-a', None, 'payload', False)
            state.admit('/aiserver.v1.BidiService/BidiAppend', b'payload-b', None, 'payload', False)
            with self.assertRaises(gateway.RelayDenied) as error:
                state.admit('/aiserver.v1.BidiService/BidiAppend', b'payload-c', None, 'payload', False)
            self.assertEqual(error.exception.reason, 'payload_request_limit')
            self.assertEqual(state.counts, {'heartbeat': 300, 'metadata': 300, 'payload': 2})

    def test_only_exact_heartbeat_is_classified_as_routine_traffic(self):
        path = '/aiserver.v1.BidiService/BidiAppend'

        def append(data):
            return field(4, data)

        self.assertEqual(gateway.request_category(path, append(field(7, b'')), 'application/proto'), 'heartbeat')
        for data in (field(7, b'') + field(2, b''), field(8, b''), field(2, b''), b''):
            self.assertEqual(gateway.request_category(path, append(data), 'application/proto'), 'payload')

    def test_protocol_allowances_are_bounded_and_local_failures_stay_fatal(self):
        with patch.dict(os.environ, {'GAB_CURSOR_METADATA_LIMIT': '1', 'GAB_CURSOR_HEARTBEAT_LIMIT': '1'}):
            for category in ('metadata', 'heartbeat'):
                state = gateway.State()
                state.admit('/same', b'a', None, category, False)
                with self.assertRaises(gateway.RelayDenied) as error:
                    state.admit('/same', b'b', None, category, False)
                self.assertEqual(error.exception.reason, category + '_request_limit')
            state = gateway.State()
            state.failed = True
            with self.assertRaises(gateway.RelayDenied) as error:
                state.admit('/x', b'', None, 'metadata', False)
            self.assertEqual(error.exception.reason, 'session_already_failed')

    def test_replay_stream_and_identity_guards_are_not_relaxed_by_accounting(self):
        state = gateway.State()
        path = '/aiserver.v1.BidiService/BidiAppend'
        state.admit(path, b'original', None, 'heartbeat', False)
        with self.assertRaises(gateway.RelayDenied) as error:
            state.admit(path, b'original', None, 'heartbeat', False)
        self.assertEqual(error.exception.reason, 'replayed_agent_request')
        state = gateway.State()
        state.admit('/agent.v1.AgentService/RunSSE', b'a', None, 'payload', True)
        with self.assertRaises(gateway.RelayDenied) as error:
            state.admit('/agent.v1.AgentService/RunSSE', b'b', None, 'payload', True)
        self.assertEqual(error.exception.reason, 'repeated_inference_stream')
        with patch.dict(os.environ, {'GAB_CURSOR_MODEL_IDENTITY': 'expected'}):
            state = gateway.State()
            with self.assertRaises(gateway.RelayDenied) as error:
                state.admit(path, b'a', {'sha256': 'changed'}, 'payload', False)
            self.assertEqual(error.exception.reason, 'model_identity_mismatch')
            self.assertFalse(state.run_started)
            state.admit(path, b'b', {'sha256': 'expected'}, 'payload', False)
            with self.assertRaises(gateway.RelayDenied) as error:
                state.admit(path, b'c', {'sha256': 'expected'}, 'payload', False)
            self.assertEqual(error.exception.reason, 'repeated_model_start')

    def test_local_rejections_are_not_reported_as_provider_outages(self):
        for row in (
            {'stage': 'request_admission', 'rejection_reason': 'metadata_request_limit'},
            {'stage': 'request_identity', 'exception_kind': 'ValueError'},
            {'stage': 'frame_dispatch', 'status': 200, 'dispatch_denial': {'reason': 'native_operation'}},
        ):
            self.assertEqual(provider_failure_cause(row), 'infrastructure_error')
        self.assertEqual(
            provider_failure_cause({'stage': 'upstream_headers', 'status': None}), 'provider_transport_error'
        )
        self.assertEqual(provider_failure_cause({'stage': 'upstream_headers', 'status': 429}), 'provider_rate_limit')

    def test_cached_catalog_and_local_telemetry_are_success_but_denials_are_fatal(self):
        from gui_agent_bench.cursor_audit import validate_provider_records

        for outcome in ('completed', 'local_metadata', 'trial_catalog_cache', 'client_closed_after_metadata'):
            row = {'outcome': outcome, 'status': 200}
            self.assertTrue(provider_record_success(row))
            validate_provider_records([row])
            for field in ('rejection_reason', 'dispatch_denial', 'provider_error'):
                self.assertFalse(provider_record_success({**row, field: 'rejected'}))
                with self.assertRaises(ValueError):
                    validate_provider_records([{**row, field: 'rejected'}])
            self.assertFalse(provider_record_success({**row, 'status': 403}))
            with self.assertRaises(ValueError):
                validate_provider_records([{**row, 'status': 403}])
        self.assertFalse(provider_record_success({'outcome': 'denied', 'status': None}))
        self.assertFalse(provider_record_success({'outcome': 'unknown', 'status': 200}))
        self.assertEqual(gateway.LOCAL_METADATA['/v1/traces'], 'application/json')
        self.assertFalse(gateway.allowed_path('/v1/traces'))
        for rows in ([], [{'outcome': 'denied', 'status': None}], [{'outcome': 'unknown', 'status': 200}]):
            with self.assertRaises(ValueError):
                validate_provider_records(rows)

    def test_relay_budget_derives_protocol_bounds_without_extra_time_or_tools(self):
        limits = budget('test_ui', 600)
        self.assertEqual(limits['profile'], 'cursor-bounded-v2')
        self.assertEqual(limits['timeout_seconds'], 600)
        self.assertEqual(limits['bridge_calls'], 800)
        self.assertEqual(limits['relay_heartbeat_requests'], 2528)
        self.assertEqual(limits['relay_metadata_requests'], 2528)
        self.assertEqual(limits['relay_payload_requests'], 3328)

    def test_explicit_model_and_no_routing_alias(self):
        value = resolve('cursor/haiku-5.5')
        self.assertEqual(value.runner, 'cursor')
        self.assertIsNone(value.reasoning_effort)
        for name in ('cursor/auto', 'cursor/default', 'cursor/a/b', 'cursor/a:1', 'cursor/../x'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                resolve(name)
        with self.assertRaises(ValueError):
            resolve('cursor/cheap', fixture_probe=True)

    def test_auth_only_selected_environment(self):
        with patch.dict(os.environ, {'CURSOR_API_KEY': 'synthetic-test-key'}, clear=True):
            self.assertEqual(credentials(), {'api_key': 'synthetic-test-key'})

    def test_external_auth_modes_and_symlinks(self):
        with tempfile.TemporaryDirectory() as name, patch.dict(os.environ, {}, clear=True):
            folder = Path(name)
            (folder / 'cursor').mkdir(mode=0o700)
            auth = folder / 'cursor/auth.json'
            auth.write_text(json.dumps({'accessToken': 'synthetic-token'}))
            auth.chmod(0o600)
            self.assertEqual(credentials(folder), {'access_token': 'synthetic-token'})
            auth.chmod(0o644)
            with self.assertRaises(ValueError):
                credentials(folder)
            auth.unlink()
            auth.symlink_to(folder / 'other')
            with self.assertRaises(OSError):
                credentials(folder)
            with self.assertRaises(ValueError):
                credentials(folder, root=folder)

    def test_render_has_no_native_tools_or_auth(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            workspace = root / 'workspace'
            workspace.mkdir()
            config = root / 'config'
            config.mkdir()
            data = b'Public instruction'
            (workspace / 'instruction.md').write_bytes(data)
            context = AuthoringContext(
                'neutral',
                'judge_visual',
                'web',
                (800, 600),
                workspace,
                {'files': {'instruction.md': digest(data)}},
                root / 'output',
                config,
                root / 'logs',
                'network',
                None,
                10,
            )
            policy = render(config, resolve('cursor/cheap'), context)
            self.assertTrue(policy['instruction'].endswith(data.decode()))
            self.assertIn('Paths under /workspace are virtual public files', policy['instruction'])
            self.assertEqual(len(policy['tools']), 4)
            self.assertNotIn('gui_dump_ui', policy['tools'])
            text = ''.join(p.read_text() for p in config.glob('*.json'))
            self.assertNotIn('accessToken', text)
            self.assertIn('Shell(*)', text)

    def test_gateway_only_fixed_rpc_paths(self):
        self.assertTrue(gateway.allowed_path('/agent.v1.AgentService/RunSSE'))
        for path in (
            'https://attacker.example/RunSSE',
            '/agent.v1.AgentService/DeleteEverything',
            '/agent.v1.AgentService/RunSSE?token=secret',
            '/../auth/token',
        ):
            with self.subTest(path=path):
                self.assertFalse(gateway.allowed_path(path))

    def test_provider_error_summary_never_retains_free_form_data(self):
        self.assertEqual(
            gateway.provider_error_summary(
                {
                    'code': 'unavailable',
                    'message': 'private',
                    'details': [{'type': 'aiserver.v1.ErrorDetails', 'value': base64.b64encode(b'\x08\x05').decode()}],
                }
            ),
            {'code': 'unavailable', 'contract_terms': [], 'cursor_error_number': 5},
        )
        self.assertEqual(
            gateway.provider_error_summary(
                {'code': 'secret', 'message': 'secret', 'details': [{'type': 'secret', 'value': 'secret'}]}
            ),
            {'code': 'unknown', 'contract_terms': []},
        )

    def test_gateway_denies_native_proto_dispatch_before_delivery(self):
        gateway.validate_server_frame(field(2, field(11, b'')), binary=True)
        for operation in (2, 3, 4, 5, 7, 8, 20, 22, 28):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                gateway.validate_server_frame(field(2, field(operation, b'')), binary=True)

    def test_independent_timing_metadata_never_bypasses_dispatch_veto(self):
        timing = field(8, b'')
        gateway.validate_server_frame(timing, binary=True)
        gateway.validate_server_frame(field(1, field(13, b'')) + timing, binary=True)
        for message in (field(2, field(2, b'')), field(1, field(9, b'')), field(7, b''), timing):
            with self.subTest(message=message), self.assertRaises(ValueError):
                gateway.validate_server_frame(message + timing, binary=True)

    def test_gateway_denies_unknown_compaction_and_reroute(self):
        for n in (9, 10, 11, 24):
            with self.subTest(n=n), self.assertRaises(ValueError):
                gateway.validate_server_frame(field(1, field(n, b'')), binary=True)
        for data in (
            field(7, b''),
            field(9, b''),
            b'\x80',
            b'\x00',
            field(2, field(11, b'')) + field(2, field(2, b'')),
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                gateway.validate_server_frame(data, binary=True)
        with self.assertRaises(ValueError):
            gateway.validate_server_frame(b'{"execServerMessage":{"shellArgs":{}}}')

    def test_gateway_extracts_pinned_model_from_gzip_append(self):
        import gzip

        run = field(1, field(9, field(1, b'cheap-model')))
        append = field(1, run.hex().encode())
        self.assertEqual(gateway.requested_model(append, 'application/proto'), 'cheap-model')
        self.assertEqual(gateway.requested_model(gzip.compress(append), 'application/proto', 'gzip'), 'cheap-model')
        self.assertIsNone(gateway.requested_model(field(1, field(7, b'').hex().encode()), 'application/proto'))

    def test_parallel_metadata_requests_keep_complete_evidence_lines(self):
        import contextlib, concurrent.futures, http.client, io, threading

        output = io.StringIO()
        server = gateway.ThreadingHTTPServer(('127.0.0.1', 0), gateway.Handler)
        server.daemon_threads = True
        server.state = gateway.State()
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def request(_):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                method = ('ListMarketplaces', 'GetTeamCommands', 'GetGlobalCommands')[_ % 3]
                connection.request('POST', '/aiserver.v1.DashboardService/' + method, b'')
                response = connection.getresponse()
                self.assertEqual(response.read(), b'')
                return response.status
            finally:
                connection.close()

        try:
            with contextlib.redirect_stdout(output), concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                self.assertEqual(list(pool.map(request, range(48))), [200] * 48)
        finally:
            server.shutdown()
            worker.join()
            server.server_close()
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(rows), 48)
        self.assertTrue(all(row['outcome'] == 'local_metadata' for row in rows))

    def test_resolved_identity_binds_parameters_and_excludes_byok(self):
        first = field(1, b'canonical-model') + field(3, field(1, b'effort') + field(2, b'low'))
        second = field(1, b'canonical-model') + field(3, field(1, b'effort') + field(2, b'high'))

        def append(identity):
            return field(1, field(1, field(9, identity)).hex().encode())

        a = gateway.requested_identity(append(first), 'application/proto')
        b = gateway.requested_identity(append(second), 'application/proto')
        self.assertEqual(a['model_id'], b['model_id'])
        self.assertNotEqual(a['sha256'], b['sha256'])
        with self.assertRaises(ValueError):
            gateway.requested_identity(append(first + field(4, b'synthetic-provider-key')), 'application/proto')

    def test_model_binding_uses_semantics_without_ignoring_parameters(self):
        model = field(1, b'gemini-model')
        effort = field(3, field(1, b'effort') + field(2, b'medium'))
        context = field(3, field(1, b'context') + field(2, b'large'))

        def identity(value):
            return gateway.requested_identity(field(4, field(1, field(9, value))), 'application/proto')

        first = identity(model + effort + context)
        reordered = identity(context + model + effort)
        self.assertEqual(first['sha256'], reordered['sha256'])
        self.assertNotEqual(first['wire_sha256'], reordered['wire_sha256'])
        self.assertEqual(first['schema'], 'requested-model-semantic-v1')
        explicit_defaults = identity(model + b'\x10\x00' + effort + context + b'\x38\x00')
        self.assertEqual(first['sha256'], explicit_defaults['sha256'])
        for changed in (
            model + context,
            model + context + field(3, field(1, b'effort') + field(2, b'high')),
            model + effort + context + b'\x10\x01',
            field(1, b'other-model') + effort + context,
        ):
            self.assertNotEqual(first['sha256'], identity(changed)['sha256'])
        for denied in (
            model + effort + effort,
            model + field(12, b'unknown'),
            model + field(3, field(1, b'context') + field(8, b'unknown')),
        ):
            with self.assertRaises(ValueError):
                identity(denied)

    def test_gateway_binary_event_stream_replaces_compression_headers(self):
        import contextlib, http.client, io, threading
        from unittest.mock import Mock

        heartbeat = field(1, field(13, b''))
        wire = b'\x00' + len(heartbeat).to_bytes(4, 'big') + heartbeat
        response = Mock(status=200, length=None)
        response.getheader.side_effect = lambda name: 'text/event-stream' if name == 'Content-Type' else None
        response.read1.side_effect = [wire, b'']
        remote = Mock()
        remote.getresponse.return_value = response
        server = gateway.ThreadingHTTPServer(('127.0.0.1', 0), gateway.Handler)
        server.daemon_threads = True
        server.state = gateway.State()
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            # Connect clients send these lowercase; adding capitalized names
            # without removing originals sends conflicting duplicate headers.
            with (
                patch.object(gateway.http.client, 'HTTPSConnection', return_value=remote),
                patch.dict(os.environ, {'GAB_CURSOR_ACCESS_TOKEN': 'synthetic-token'}),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                connection.request(
                    'POST',
                    '/agent.v1.AgentService/RunSSE',
                    b'',
                    {
                        'accept-encoding': 'gzip',
                        'connect-accept-encoding': 'gzip',
                        'x-cursor-agent-allowed-tools': 'mcp_tool_call,get_mcp_tools_tool_call',
                    },
                )
                received = connection.getresponse()
                self.assertEqual(received.status, 200)
                self.assertEqual(received.read(), wire)
            sent = remote.request.call_args.kwargs['headers']
            for key in ('accept-encoding', 'connect-accept-encoding'):
                self.assertEqual([(k, v) for k, v in sent.items() if k.lower() == key], [(key.title(), 'identity')])
            connection.close()
        finally:
            server.shutdown()
            worker.join()
            server.server_close()

    def test_gateway_never_delivers_credential_echo_or_native_dispatch(self):
        import contextlib, http.client, io, threading
        from unittest.mock import Mock

        token = b'synthetic-token'

        def wire(payload):
            return b'\x00' + len(payload).to_bytes(4, 'big') + payload

        cases = [
            (False, [b'prefix-synthetic-', b'token-suffix'], 'response_credentials'),
            (True, [wire(field(1, field(1, token)))], 'response_credentials'),
            (True, [wire(field(2, field(2, b'native-command')))], 'frame_dispatch'),
        ]
        for streaming, parts, stage in cases:
            with self.subTest(streaming=streaming, stage=stage):
                response = Mock(status=200, length=None)
                media = 'application/connect+proto' if streaming else 'application/proto'
                response.getheader.side_effect = lambda name: media if name == 'Content-Type' else None
                response.read1.side_effect = [*parts, b'']
                remote = Mock()
                remote.getresponse.return_value = response
                server = gateway.ThreadingHTTPServer(('127.0.0.1', 0), gateway.Handler)
                server.daemon_threads = True
                server.state = gateway.State()
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                output = io.StringIO()
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                try:
                    with (
                        patch.object(gateway.http.client, 'HTTPSConnection', return_value=remote),
                        patch.dict(os.environ, {'GAB_CURSOR_ACCESS_TOKEN': token.decode()}),
                        contextlib.redirect_stdout(output),
                    ):
                        path = '/agent.v1.AgentService/RunSSE' if streaming else '/aiserver.v1.DashboardService/GetMe'
                        connection.request(
                            'POST', path, b'', {'x-cursor-agent-allowed-tools': 'mcp_tool_call,get_mcp_tools_tool_call'}
                        )
                        received = connection.getresponse()
                        with self.assertRaises(http.client.IncompleteRead) as error:
                            received.read()
                        self.assertEqual(error.exception.partial, b'')
                    record = json.loads(output.getvalue())
                    self.assertEqual(record['stage'], stage)
                    self.assertEqual(record['outcome'], 'failed')
                    self.assertNotIn(token.decode(), output.getvalue())
                    self.assertNotIn('native-command', output.getvalue())
                finally:
                    connection.close()
                    server.shutdown()
                    worker.join()
                    server.server_close()

    def run_capture(self, events):
        events = [*events, {'type': 'bench_child_exit', 'exit_code': 0}]
        code = (
            'import sys;sys.stdout.write('
            + repr(''.join(json.dumps(e) + '\n' for e in events))
            + ');sys.stdout.flush()'
        )
        with tempfile.TemporaryDirectory() as name:
            process = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                return capture(process, Path(name), budget('judge_visual', 5))
            finally:
                process.wait(timeout=5)

    def test_capture_requires_terminal_event(self):
        with self.assertRaises(Failure):
            self.run_capture([{'type': 'system', 'subtype': 'init'}])

    def test_known_reconnect_fails_as_transport_without_admitting_replay(self):
        event = {'type': 'connection', 'subtype': 'reconnecting', 'attempt': 1, 'endpoint_url': 'http://provider:8080'}
        with self.assertRaises(Failure) as error:
            self.run_capture(
                [
                    {'type': 'system', 'subtype': 'init'},
                    event,
                    {'type': 'result', 'subtype': 'success', 'is_error': False},
                ]
            )
        self.assertEqual(error.exception.cause, 'provider_transport_error')
        for change in (
            {'subtype': 'connected'},
            {'attempt': 2},
            {'attempt': True},
            {'endpoint_url': 'https://unexpected.example'},
        ):
            with self.subTest(change=change), self.assertRaises(Failure) as error:
                self.run_capture([{'type': 'system', 'subtype': 'init'}, {**event, **change}])
            self.assertEqual(error.exception.cause, 'incomplete_trajectory')

    def test_twenty_minute_budget_preserves_action_and_evidence_limits(self):
        old, new = budget('test_ui', 600), budget('test_ui', 1200)
        self.assertEqual(new['timeout_seconds'], 1200)
        changed = {k for k in old if old[k] != new[k]}
        self.assertEqual(changed, {'timeout_seconds', 'relay_heartbeat_requests', 'relay_metadata_requests'})

    def test_capture_accepts_empty_tool_session(self):
        result = self.run_capture(
            [{'type': 'system', 'subtype': 'init'}, {'type': 'result', 'subtype': 'success', 'is_error': False}]
        )
        self.assertTrue(result['completed'])
        self.assertIsNone(result['provider_cost_usd'])

    def test_capture_live_tool_metadata_preserves_exact_operation_check(self):
        def event(subtype, operation):
            return {
                'type': 'tool_call',
                'subtype': subtype,
                'call_id': 'x',
                'tool_call': {
                    operation: {},
                    'toolCallId': 'x',
                    'startedAtMs': '1',
                    'completedAtMs': '2',
                    'hookAdditionalContexts': [],
                },
            }

        self.assertTrue(
            self.run_capture(
                [
                    {'type': 'system', 'subtype': 'init'},
                    event('started', 'mcpToolCall'),
                    event('completed', 'mcpToolCall'),
                    {'type': 'result', 'subtype': 'success', 'is_error': False},
                ]
            )['completed']
        )
        with self.assertRaises(Failure):
            self.run_capture([{'type': 'system', 'subtype': 'init'}, event('started', 'shellToolCall')])
        ambiguous = event('started', 'mcpToolCall')
        ambiguous['tool_call']['unknownMetadata'] = {}
        with self.assertRaises(Failure) as error:
            self.run_capture([{'type': 'system', 'subtype': 'init'}, ambiguous])
        self.assertEqual(error.exception.cause, 'incomplete_trajectory')

    def test_capture_rejects_native_and_incomplete_tools(self):
        for tool in ('shellToolCall', 'readToolCall', 'taskToolCall'):
            with self.subTest(tool=tool), self.assertRaises(Failure):
                self.run_capture(
                    [
                        {'type': 'system', 'subtype': 'init'},
                        {'type': 'tool_call', 'subtype': 'started', 'call_id': 'x', 'tool_call': {tool: {}}},
                    ]
                )
        with self.assertRaises(Failure):
            self.run_capture(
                [
                    {'type': 'system', 'subtype': 'init'},
                    {'type': 'tool_call', 'subtype': 'started', 'call_id': 'x', 'tool_call': {'mcpToolCall': {}}},
                    {'type': 'result', 'subtype': 'success', 'is_error': False},
                ]
            )


if __name__ == '__main__':
    unittest.main()
