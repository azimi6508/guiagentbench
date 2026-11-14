"""Fault-injected production privacy RPC tests; no account or model requests."""

import concurrent.futures
import contextlib
import http.client
import importlib.util
import json
import io
import os
from pathlib import Path
import socketserver
import threading
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
SOURCE = Path(os.environ.get('GAB_CURSOR_TEST_GATEWAY_PATH', ROOT / 'runtime/cursor/gateway.py'))
spec = importlib.util.spec_from_file_location('privacy_gateway', SOURCE)
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)
PRIVACY = '/aiserver.v1.DashboardService/GetUserPrivacyMode'
VALUE = b'\x08\x02\x18\x01\x38\x02'


class Harness:
    def __init__(self, responses):
        self.responses = responses
        self.sent = []
        self.rows = []
        self.now = 1000.0
        self.lock = threading.Lock()
        self.done = threading.Condition()
        server_type = getattr(gateway, 'GatewayHTTPServer', gateway.ThreadingHTTPServer)
        self.server = server_type(('127.0.0.1', 0), gateway.Handler)
        self.server.daemon_threads = True
        self.server.state = gateway.State()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def remote(self, *_args, **_kwargs):
        with self.lock:
            index = len(self.sent)
            configured = self.responses[min(index, len(self.responses) - 1)]
            self.sent.append(configured)
        response = Mock(status=configured.get('status', 200), length=0)
        headers = {'Content-Type': 'application/proto', **configured.get('headers', {})}
        response.getheader.side_effect = lambda name: headers.get(name)
        response.read1.side_effect = [configured.get('body', VALUE), b'']
        remote = Mock()
        remote.getresponse.return_value = response
        return remote

    def record(self, row):
        with self.done:
            self.rows.append(row)
            self.done.notify_all()

    def __enter__(self):
        self.environment = patch.dict(
            os.environ, {'GAB_CURSOR_ACCESS_TOKEN': 'synthetic-only-token', 'GAB_CURSOR_METADATA_LIMIT': '1000'}
        )
        self.remote_patch = patch.object(gateway.http.client, 'HTTPSConnection', side_effect=self.remote)
        self.record_patch = patch.object(gateway, 'record', side_effect=self.record)
        self.time_patch = patch.object(gateway, 'time', types.SimpleNamespace(monotonic=lambda: self.now), create=True)
        for item in (self.environment, self.remote_patch, self.record_patch, self.time_patch):
            item.start()
        self.thread.start()
        return self

    def request(self, path=PRIVACY, body=b''):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request('POST', path, body, {'Content-Type': 'application/proto'})
            response = connection.getresponse()
            return response.status, response.read()
        except (http.client.RemoteDisconnected, http.client.IncompleteRead):
            return None, None
        finally:
            connection.close()

    def wait_rows(self, count):
        with self.done:
            if not self.done.wait_for(lambda: len(self.rows) == count, timeout=5):
                raise AssertionError('Exactly one audit record per synthetic request is required')

    def __exit__(self, *_):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        for item in (self.time_patch, self.record_patch, self.remote_patch, self.environment):
            item.stop()


class GatewayPrivacyTests(unittest.TestCase):
    def test_reset_before_request_line_is_typed_nonfatal_and_does_not_poison_rpc(self):
        class Reader:
            def __init__(self, inner):
                self.inner = inner

            def readline(self, *args):
                raise ConnectionResetError('synthetic idle reset')

            def __getattr__(self, name):
                return getattr(self.inner, name)

        class Handler(gateway.Handler):
            def setup(self):
                super().setup()
                self.rfile = Reader(self.rfile)

        with Harness([{}]) as h:
            h.server.RequestHandlerClass = Handler
            self.assertEqual(h.request(), (None, None))
            h.wait_rows(1)
            self.assertEqual(h.rows[0]['outcome'], 'client_closed_before_request')
            self.assertFalse(h.server.state.failed)
            self.assertEqual(len(h.sent), 0)
            h.server.RequestHandlerClass = gateway.Handler
            self.assertEqual(h.request(), (200, VALUE))
            h.wait_rows(2)
            self.assertEqual(len(h.sent), 1)

    def test_unknown_pre_request_error_is_structured_fatal_without_raw_exception_data(self):
        class Reader:
            def __init__(self, inner):
                self.inner = inner

            def readline(self, *args):
                raise OSError('private synthetic exception content')

            def __getattr__(self, name):
                return getattr(self.inner, name)

        class Handler(gateway.Handler):
            def setup(self):
                super().setup()
                self.rfile = Reader(self.rfile)

        stderr = io.StringIO()
        with Harness([{}]) as h, contextlib.redirect_stderr(stderr):
            h.server.RequestHandlerClass = Handler
            self.assertEqual(h.request(), (None, None))
            h.wait_rows(1)
            self.assertEqual(h.rows[0]['outcome'], 'failed')
            self.assertEqual(h.rows[0]['rejection_reason'], 'unclassified_http_connection_error')
            self.assertTrue(h.server.state.failed)
            self.assertTrue(h.rows[0]['frames'])
            self.assertNotIn('private synthetic', json.dumps(h.rows))
            self.assertEqual(stderr.getvalue(), '')

    def test_reset_after_request_line_is_not_the_idle_exception(self):
        class Reader:
            def __init__(self, inner):
                self.inner, self.started = inner, False

            def readline(self, *args):
                if not self.started:
                    self.started = True
                    return b'POST /aiserver.v1.DashboardService/GetUserPrivacyMode HTTP/1.1\r\n'
                raise ConnectionResetError('synthetic reset during headers')

            def __getattr__(self, name):
                return getattr(self.inner, name)

        class Handler(gateway.Handler):
            def setup(self):
                super().setup()
                self.rfile = Reader(self.rfile)

        with Harness([{}]) as h:
            h.server.RequestHandlerClass = Handler
            self.assertEqual(h.request(), (None, None))
            h.wait_rows(1)
            self.assertEqual(h.rows[0]['outcome'], 'failed')
            self.assertTrue(h.server.state.failed)
            self.assertEqual(len(h.sent), 0)

    def test_cancelled_cached_reply_preserves_session_and_valid_capture(self):
        original_write = socketserver._SocketWriter.write
        for error in (BrokenPipeError, ConnectionResetError):
            for phase in ('headers', 'body'):
                with self.subTest(error=error, phase=phase), Harness([{}]) as h:
                    self.assertEqual(h.request(), (200, VALUE))
                    h.wait_rows(1)
                    failed = []

                    def write(stream, data):
                        target = data.startswith(b'HTTP/1.1 200') if phase == 'headers' else data == VALUE
                        if target and not failed:
                            failed.append(True)
                            raise error('synthetic client cancellation')
                        return original_write(stream, data)

                    with patch.object(socketserver._SocketWriter, 'write', write):
                        self.assertEqual(h.request(), (None, None))
                    h.wait_rows(2)
                    self.assertEqual(h.rows[1]['outcome'], 'client_closed_after_metadata')
                    self.assertEqual(h.rows[1]['status'], 200)
                    self.assertEqual(h.rows[1]['privacy_snapshot']['event'], 'served')
                    self.assertFalse(h.server.state.failed)
                    self.assertEqual(h.request(), (200, VALUE))
                    h.wait_rows(3)
                    self.assertEqual(len(h.sent), 1)

    def test_unknown_cached_write_failure_remains_fatal(self):
        original_write = socketserver._SocketWriter.write
        with Harness([{}]) as h:
            self.assertEqual(h.request(), (200, VALUE))
            h.wait_rows(1)

            def write(stream, data):
                if data == VALUE:
                    raise OSError('synthetic unknown write failure')
                return original_write(stream, data)

            with patch.object(socketserver._SocketWriter, 'write', write):
                self.assertEqual(h.request(), (None, None))
            h.wait_rows(2)
            self.assertEqual(h.rows[1]['outcome'], 'failed')
            self.assertTrue(h.server.state.failed)
            self.assertEqual(h.request(), (None, None))
            h.wait_rows(3)
            self.assertEqual(len(h.sent), 1)

    def test_redundant_reads_use_exact_success_not_second_upstream_502(self):
        with Harness([{}, {'status': 502, 'body': b'upstream failed'}]) as h:
            self.assertEqual(h.request(), (200, VALUE))
            for _ in range(20):
                self.assertEqual(h.request(), (200, VALUE))
            h.wait_rows(21)
            self.assertEqual(len(h.sent), 1)
            self.assertEqual(h.server.state.counts['metadata'], 21)
            self.assertFalse(h.server.state.failed)
            self.assertEqual(h.rows[0]['privacy_snapshot']['event'], 'captured')
            self.assertTrue(all(r['outcome'] == 'trial_privacy_cache' for r in h.rows[1:]))
            self.assertNotIn('synthetic-only-token', json.dumps(h.rows))

    def test_concurrent_identical_reads_fetch_once_and_capture_precedes_hits(self):
        with Harness([{}]) as h, concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(list(pool.map(lambda _: h.request(), range(24))), [(200, VALUE)] * 24)
            h.wait_rows(24)
            self.assertEqual(len(h.sent), 1)
            self.assertEqual(h.rows[0]['privacy_snapshot']['event'], 'captured')
            self.assertEqual([r['privacy_snapshot']['generation'] for r in h.rows], [1] * 24)

    def test_first_failure_is_not_cached_retried_or_replaced(self):
        with Harness([{'status': 502, 'body': b'failed'}, {}]) as h:
            self.assertEqual(h.request(), (502, b'failed'))
            self.assertEqual(h.request(), (None, None))
            h.wait_rows(2)
            self.assertEqual(len(h.sent), 1)
            self.assertIsNone(h.server.state.privacy_cache)
            self.assertEqual(h.rows[0]['outcome'], 'provider_error')
            self.assertEqual(h.rows[1]['rejection_reason'], 'session_already_failed')

    def test_expiry_fetches_changed_authoritative_value(self):
        changed = b'\x08\x01'
        with Harness([{}, {'body': changed}]) as h:
            self.assertEqual(h.request(), (200, VALUE))
            h.now += gateway.PRIVACY_CACHE_SECONDS
            self.assertEqual(h.request(), (200, changed))
            h.wait_rows(2)
            self.assertEqual(len(h.sent), 2)
            self.assertEqual(h.rows[1]['privacy_snapshot']['generation'], 2)

    def test_failed_refresh_never_falls_back_to_stale_success(self):
        with Harness([{}, {'status': 502, 'body': b'failed'}, {}]) as h:
            self.assertEqual(h.request(), (200, VALUE))
            h.now += gateway.PRIVACY_CACHE_SECONDS
            self.assertEqual(h.request(), (502, b'failed'))
            self.assertEqual(h.request(), (None, None))
            h.wait_rows(3)
            self.assertEqual(len(h.sent), 2)
            self.assertTrue(h.server.state.failed)

    def test_changed_request_fetches_fresh_instead_of_using_previous_team(self):
        with Harness([{}, {'body': b'\x08\x01'}]) as h:
            self.assertEqual(h.request(), (200, VALUE))
            self.assertEqual(h.request(body=b'\x10\x01'), (200, b'\x08\x01'))
            self.assertEqual(h.request(body=b'\x10\x01'), (200, b'\x08\x01'))
            h.wait_rows(3)
            self.assertEqual(len(h.sent), 2)
            self.assertNotEqual(
                h.rows[0]['privacy_snapshot']['request_sha256'], h.rows[1]['privacy_snapshot']['request_sha256']
            )

    def test_other_metadata_is_not_cached(self):
        with Harness([{}]) as h:
            for _ in range(2):
                self.assertEqual(h.request('/aiserver.v1.DashboardService/GetMe'), (200, VALUE))
            h.wait_rows(2)
            self.assertEqual(len(h.sent), 2)
            self.assertTrue(all('privacy_snapshot' not in r for r in h.rows))

    def test_cached_reads_still_consume_original_metadata_budget(self):
        with Harness([{}]) as h, patch.dict(os.environ, {'GAB_CURSOR_METADATA_LIMIT': '1'}):
            self.assertEqual(h.request(), (200, VALUE))
            self.assertEqual(h.request(), (None, None))
            h.wait_rows(2)
            self.assertEqual(len(h.sent), 1)
            self.assertEqual(h.rows[-1]['rejection_reason'], 'metadata_request_limit')

    def test_cache_never_survives_a_new_trial_state(self):
        with Harness([{}, {'body': b'\x08\x01'}]) as h:
            self.assertEqual(h.request(), (200, VALUE))
            h.wait_rows(1)
            h.server.state = gateway.State()
            self.assertEqual(h.request(), (200, b'\x08\x01'))
            h.wait_rows(2)
            self.assertEqual(len(h.sent), 2)

    def test_bad_wire_rpc_error_compression_and_credentials_are_never_cached(self):
        cases = [
            {'body': b'\x80'},
            {'body': b'\x08\x09'},
            {'body': b'\x18\x02'},
            {'body': b'\x08\x01\x08\x02'},
            {'body': b'\x42\x00'},
            {'body': b'synthetic-only-token'},
            {'headers': {'Grpc-Status': '13'}},
            {'headers': {'Content-Type': 'application/json'}, 'body': b'{"error":true}'},
            {'headers': {'Content-Encoding': 'gzip'}},
        ]
        for response in cases:
            with self.subTest(response=response), Harness([response]) as h:
                self.assertEqual(h.request(), (None, None))
                h.wait_rows(1)
                self.assertIsNone(h.server.state.privacy_cache)
                self.assertTrue(h.server.state.failed)


class PrivacyAuditTests(unittest.TestCase):
    def test_live_records_require_exact_upstream_capture_and_current_generation(self):
        from gui_agent_bench.cursor_audit import validate_provider_records
        from gui_agent_bench.runners.cursor import provider_record_success

        with Harness([{}]) as h:
            h.request()
            h.request()
            h.wait_rows(2)
            rows = json.loads(json.dumps(h.rows))
        validate_provider_records(rows)
        cancelled = json.loads(json.dumps(rows))
        cancelled[1].update(outcome='client_closed_after_metadata', exception_kind='BrokenPipeError')
        validate_provider_records(cancelled)
        for error in ('OSError', 'TimeoutError', None):
            changed = json.loads(json.dumps(cancelled))
            changed[1]['exception_kind'] = error
            self.assertFalse(provider_record_success(changed[1]))
        with self.assertRaises(ValueError):
            validate_provider_records(cancelled[1:])
        with self.assertRaises(ValueError):
            validate_provider_records(rows[1:])
        for field, value in [
            ('response_sha256', 'f' * 64),
            ('request_sha256', 'e' * 64),
            ('generation', 2),
            ('age_ms', 60_000),
            ('age_ms', -1),
        ]:
            changed = json.loads(json.dumps(rows))
            changed[1]['privacy_snapshot'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_provider_records(changed)
        for field, value in [
            ('path', '/agent.v1.AgentService/RunSSE'),
            ('sent_bytes', 1),
            ('status', 502),
            ('dispatch_denial', {'reason': 'denied'}),
            ('rejection_reason', 'session_already_failed'),
        ]:
            self.assertFalse(provider_record_success({**rows[1], field: value}))


if __name__ == '__main__':
    unittest.main()
