import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from http.server import HTTPServer
import urllib.request
import urllib.error

from gui_agent_bench.authoring_recovery import (
    AuthoringRecovery,
    VERSION,
    LIMIT,
    audit_recovery_events,
    recovery_from_result,
    recovery_result,
)
from gui_agent_bench.failures import Failure
from gui_agent_bench.codex_bridge import Bridge
from gui_agent_bench.io import digest


class RecoveryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.records = []
        self.reset = Mock()
        self.r = AuthoringRecovery('mobile', self.reset, lambda **v: self.records.append(v))

    def test_recover_known_scope_loss_with_failed_action_and_reset_evidence(self):
        result, failure, marker = self.r.handle(Failure('app_scope_lost'), 'step')
        self.assertTrue(result['isError'])
        self.assertEqual(failure['cause'], 'app_scope_lost')
        self.reset.assert_called_once_with()
        self.r.check()
        self.assertEqual(recovery_from_result(result, 'mobile', 'gui_step'), marker)
        self.records.append(dict(tool='step', operation_failed=True, denied=False, failure=failure, recovery=marker))
        self.assertEqual(audit_recovery_events(self.records, 'mobile'), [marker])
        with self.assertRaises(ValueError):
            audit_recovery_events(self.records[:-1], 'mobile')
        with self.assertRaises(ValueError):
            audit_recovery_events(self.records[1:], 'mobile')

    def test_unknown_policy_setup_and_reset_errors_are_not_recovered(self):
        for cause in (
            'unknown_operation_error',
            'policy_violation',
            'app_not_ready',
            'reset_failure',
            'infrastructure_error',
            'evidence_overflow',
        ):
            result, _, marker = self.r.handle(Failure(cause), 'step')
            self.assertIsNone(marker)
        self.r.handle(Failure('app_scope_lost'), 'reset')
        for platform in ('web', 'tv'):
            AuthoringRecovery(platform, self.reset, lambda **v: None).handle(Failure('app_scope_lost'), 'step')
        self.reset.assert_not_called()

    def test_failed_reset_and_exhaustion_do_not_retry_or_resume(self):
        self.reset.side_effect = RuntimeError('private data')
        result, _, marker = self.r.handle(Failure('app_scope_lost'), 'observe')
        self.assertIsNone(marker)
        self.assertEqual(json.loads(result['content'][0]['text'])['cause'], 'reset_failure')
        self.assertNotIn('private data', json.dumps(self.records))
        with self.assertRaises(Failure):
            self.r.check()
        self.r.handle(Failure('app_scope_lost'), 'step')
        self.reset.assert_called_once()
        with self.assertRaises(ValueError):
            audit_recovery_events(self.records, 'mobile')
        self.reset.reset_mock(side_effect=True)
        r = AuthoringRecovery('mobile', self.reset, lambda **v: None)
        for _ in range(LIMIT):
            self.assertIsNotNone(r.handle(Failure('app_scope_lost'), 'step')[2])
        result, _, marker = r.handle(Failure('app_scope_lost'), 'step')
        self.assertIsNone(marker)
        self.assertEqual(self.reset.call_count, LIMIT)
        self.assertEqual(json.loads(result['content'][0]['text'])['cause'], 'budget_exhausted')

    def test_native_profiles_report_scope_loss_without_observing_other_apps(self):
        from gui_agent_bench.mobile_driver import Driver

        for cls, module in [(Driver, 'mobile_driver')]:
            driver = object.__new__(cls)
            driver.device = Mock()
            driver.package = 'org.example.app'
            with patch('gui_agent_bench.' + module + '.focused_package', return_value='outside.app'):
                with self.assertRaises(Failure) as caught:
                    driver.nodes()
            self.assertEqual(caught.exception.cause, 'app_scope_lost')
            driver.device.dump_hierarchy.assert_not_called()

    def test_bridge_continues_only_for_exact_ordered_native_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / 'workspace'
            workspace.mkdir()
            output = root / 'output'
            output.mkdir()
            (workspace / 'instruction.md').write_bytes(b'public')
            manifest = {'files': {'instruction.md': digest(b'public')}}
            marker = {'version': VERSION, 'sequence': 1, 'operation': 'step', 'status': 'reset'}
            broker = Mock()
            broker.request.return_value = recovery_result(marker)
            bridge = Bridge(
                workspace, output, root / 'audit', manifest, 'test_visual', 'mobile', (720, 1280), broker=broker
            )
            self.assertTrue(bridge.call('gui_step', {'action': 'press', 'key': 'Escape'}, 1)['isError'])
            self.assertFalse(bridge.fatal)
            self.assertFalse(bridge.call('bench_list_files', {}, 2)['isError'])
            bridge.call('gui_step', {'action': 'press', 'key': 'Escape'}, 3)
            self.assertTrue(bridge.fatal)  # replayed sequence is not recovery
            self.assertTrue(bridge.call('bench_list_files', {}, 4)['isError'])


@contextlib.contextmanager
def broker_server(kind, mode='author', reset_error=False):
    from gui_agent_bench import broker, oracle_broker
    from PIL import Image

    png = io.BytesIO()
    Image.new('RGB', (720, 1280), 'white').save(png, format='PNG')
    adapter = Mock()
    adapter.observe.return_value = png.getvalue()
    adapter.dump_ui.return_value = '[]'
    adapter.visual_step.side_effect = Failure('app_scope_lost')
    adapter.user_step.side_effect = Failure('app_scope_lost')
    if reset_error:
        adapter.reset.side_effect = [None, Failure('infrastructure_error')]
    ready = threading.Event()
    servers = []

    def factory(address, handler):
        server = HTTPServer(('127.0.0.1', 0), handler)
        servers.append(server)
        ready.set()
        return server

    module = broker if kind == 'judge_test' else oracle_broker
    output = io.StringIO()
    with (
        tempfile.TemporaryDirectory() as temp,
        contextlib.redirect_stdout(output),
        patch('gui_agent_bench.adapters.factory.adapter_for', return_value=adapter),
        patch('gui_agent_bench.oracle_broker.adapter_for', return_value=adapter),
        patch('gui_agent_bench.oracle_broker.ImageAssertions'),
        patch.object(module, 'HTTPServer', side_effect=factory),
    ):
        target = (
            (lambda: broker.serve((720, 1280), platform='mobile'))
            if kind == 'judge_test'
            else lambda: oracle_broker.serve(
                kind, mode, Path(temp) / 'source.py', (720, 1280), platform='mobile', reference_root=Path(temp) / 'refs'
            )
        )
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        if not ready.wait(5):
            raise RuntimeError('broker failed startup')

        def call(name, args):
            body = (
                {'operation': name, 'arguments': args}
                if mode == 'execute'
                else {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}}
            )
            request = urllib.request.Request(
                'http://%s:%s/%s' % (*servers[0].server_address, 'call' if mode == 'execute' else 'mcp'),
                data=json.dumps(body).encode(),
                headers={'Content-Type': 'application/json'},
            )
            try:
                with urllib.request.urlopen(request) as r:
                    return r.status, json.load(r)
            except urllib.error.HTTPError as e:
                return e.code, json.load(e)

        try:
            yield call, adapter, output
        finally:
            servers[0].shutdown()
            thread.join(5)


class BrokerRecoveryTests(unittest.TestCase):
    def test_both_authoring_brokers_reset_and_continue(self):
        for kind in ('judge_test', 'test_visual', 'test_ui'):
            with self.subTest(kind=kind), broker_server(kind) as (call, adapter, logs):
                status, result = call('step', {'action': 'press', 'key': 'Escape'})
                self.assertEqual(status, 200)
                self.assertTrue(result['result']['isError'])
                self.assertEqual(adapter.reset.call_count, 2)
                self.assertFalse(call('observe', {})[1]['result']['isError'])
                records = [json.loads(line) for line in logs.getvalue().splitlines()]
                self.assertEqual(len(audit_recovery_events(records, 'mobile')), 1)

    def test_execution_never_recovers_even_for_the_same_failure(self):
        with broker_server('test_visual', 'execute') as (call, adapter, logs):
            status, result = call('step', {'action': 'press', 'key': 'Escape'})
            self.assertEqual(status, 400)
            self.assertEqual(result['cause'], 'app_scope_lost')
            self.assertEqual(adapter.reset.call_count, 1)
            self.assertNotIn('recovery_event', logs.getvalue())
            from gui_agent_bench.verifier.oracle import classify

            records = [json.loads(line) for line in logs.getvalue().splitlines()]
            self.assertEqual(classify(records, 0, full_test=True)['outcome'], 'INVALID')

    def test_failed_automatic_reset_prevents_subsequent_observation(self):
        with broker_server('test_visual', reset_error=True) as (call, adapter, logs):
            result = call('step', {'action': 'press', 'key': 'Escape'})[1]['result']
            self.assertEqual(json.loads(result['content'][0]['text'])['cause'], 'reset_failure')
            self.assertTrue(call('observe', {})[1]['result']['isError'])
            adapter.observe.assert_not_called()
            self.assertEqual(adapter.reset.call_count, 2)
