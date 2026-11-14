"""Failure attribution must be evidence-based, safe and scoring-neutral."""

from contextlib import redirect_stdout, contextmanager
from http.server import HTTPServer
from io import StringIO, BytesIO
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import Mock, patch

import test_http_transport
from test_http_transport import running_broker
from gui_agent_bench import broker, oracle_broker, gateway
from gui_agent_bench.failures import Failure, issue, diagnostics, summarize
from gui_agent_bench.budgets import EXECUTIONS_PER_VERSION
from gui_agent_bench.verifier.oracle import classify, pair_result
from gui_agent_bench.verifier.judge import grade
from gui_agent_bench.runners.opencode import event_issues
from gui_agent_bench.adapters.mobile import MobileAdapter


class FailureTests(unittest.TestCase):
    exchange = test_http_transport.BrokerHTTPTests.exchange

    def test_http_separates_policy_arguments_and_runtime_failures_without_leaking(self):
        cases = [
            ('policy_violation', {'action': 'evaluate', 'code': '1+1'}, None),
            ('invalid_arguments', {'action': 'click', 'x': 1}, None),
            (
                'target_unavailable',
                {'action': 'click', 'role': 'button', 'name': 'Save'},
                Failure('target_unavailable'),
            ),
            (
                'action_timeout',
                {'action': 'click', 'role': 'button', 'name': 'Save'},
                TimeoutError('SECRET /private/labels.json'),
            ),
            (
                'unknown_operation_error',
                {'action': 'click', 'role': 'button', 'name': 'Save'},
                RuntimeError('SECRET /private/labels.json'),
            ),
        ]
        for module, mode in [(broker, 'author'), (oracle_broker, 'author'), (oracle_broker, 'execute')]:
            for cause, args, error in cases:
                adapter, output = Mock(), StringIO()
                adapter.user_step.side_effect = error
                with (
                    self.subTest(module=module.__name__, mode=mode, cause=cause),
                    redirect_stdout(output),
                    running_broker(module, mode, adapter=adapter) as address,
                ):
                    body = (
                        {'operation': 'step', 'arguments': args}
                        if mode == 'execute'
                        else {
                            'jsonrpc': '2.0',
                            'id': 1,
                            'method': 'tools/call',
                            'params': {'name': 'step', 'arguments': args},
                        }
                    )
                    status, response = self.exchange(address, 'POST', '/call' if mode == 'execute' else '/mcp', body)
                    self.assertEqual(status, 400 if mode == 'execute' else 200)
                self.assertNotIn('SECRET', output.getvalue() + json.dumps(response))
                records = [json.loads(line) for line in output.getvalue().splitlines()]
                failed = [r for r in records if 'failure' in r]
                self.assertEqual(len(failed), 1)
                self.assertEqual(failed[0]['failure']['cause'], cause)
                self.assertEqual(failed[0]['denied'], cause == 'policy_violation')
                self.assertTrue(failed[0]['operation_failed'])
                self.assertEqual(failed[0]['failure']['impact'], 'zero_credit' if mode == 'execute' else 'feedback')

    def test_reset_retains_underlying_failure_and_evidence_overflow_is_not_policy(self):
        adapter, output = Mock(), StringIO()
        with redirect_stdout(output), running_broker(oracle_broker, adapter=adapter) as address:
            adapter.reset.side_effect = TimeoutError('SECRET')
            for name in ('reset', 'dump_ui'):
                adapter.dump_ui.return_value = 'x' * 32001
                _, response = self.exchange(
                    address,
                    'POST',
                    '/mcp',
                    {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': {}}},
                )
                self.assertTrue(response['result']['isError'])
        failures = [r['failure'] for r in map(json.loads, output.getvalue().splitlines()) if 'failure' in r]
        self.assertEqual([f['cause'] for f in failures], ['reset_failure', 'evidence_overflow'])
        self.assertEqual(failures[0]['underlying_causes'], ['action_timeout'])
        self.assertNotIn('SECRET', output.getvalue())

    def test_all_failures_survive_without_changing_legacy_outcome_priority(self):
        records = [
            {
                'denied': True,
                'operation_failed': True,
                'failure': issue(Failure('policy_violation'), phase='execution', operation='ui', impact='zero_credit'),
            }
        ]
        result = classify(records, 1, 'TIMEOUT', termination_causes=['TIMEOUT', 'RESOURCE_LIMIT'])
        self.assertEqual(result['outcome'], 'TIMEOUT')
        self.assertEqual(
            [i['cause'] for i in result['diagnostics']['issues']],
            ['policy_violation', 'execution_timeout', 'resource_limit', 'process_error'],
        )
        self.assertEqual(result['diagnostics']['primary_issue'], 0)
        self.assertEqual(pair_result([result, result])['reward'], 0)

    def test_caught_ordinary_operation_failure_still_prevents_credit(self):
        records = [
            {
                'operation_failed': True,
                'denied': False,
                'failure': issue(
                    Failure('target_unavailable'), phase='execution', operation='step', impact='zero_credit'
                ),
            }
        ]
        result = classify(records, 0)
        self.assertEqual(result['outcome'], 'INVALID')
        self.assertEqual(result['diagnostics']['issues'][0]['cause'], 'target_unavailable')

    def test_historical_denials_stay_ambiguous_and_assertion_causes_remain_distinct(self):
        from test_oracle import record

        result = classify([{'denied': True}, record('setup', False, True), record('behavior', False)], 0)
        self.assertEqual(
            [i['cause'] for i in result['diagnostics']['issues']],
            ['legacy_ambiguous_denial', 'failed_precondition', 'behavioral_mismatch'],
        )
        self.assertEqual(result['diagnostics']['issues'][1]['source']['record_index'], 1)

    def test_pair_comparison_rejects_changed_assertions_without_relabeling_as_bug(self):
        from test_oracle import record

        first = classify([record('setup', True, True), record('x', True)], 0)
        second = classify([record('setup', True, True), record('y', False)], 0)
        result = pair_result([first, second] * EXECUTIONS_PER_VERSION)
        self.assertEqual(result['reward'], 0)
        self.assertEqual(result['diagnostics']['issues'][-1]['cause'], 'incomparable_pair')

    def test_missing_and_malformed_submissions_are_distinguishable(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            labels, submission = folder / 'labels.json', folder / 'submission.json'
            labels.write_text('{"correct":"PASS","faulty":"FAIL"}')
            for cause, data in [('missing_submission', None), ('malformed_submission', '{bad')]:
                if data is not None:
                    submission.write_text(data)
                result = grade(submission, labels, 'correct', folder / 'out')
                self.assertEqual(result['reward'], 0)
                self.assertEqual(result['diagnostics']['issues'][0]['cause'], cause)

    def test_runner_preserves_overflow_and_incomplete_completion(self):
        found = event_issues(
            [{'type': 'error'}, {'type': 'compaction'}, {'type': 'tool_use', 'part': {'truncated': True}}]
        )
        self.assertEqual(
            [f['cause'] for f in found],
            ['unknown_operation_error', 'context_overflow', 'evidence_overflow', 'incomplete_trajectory'],
        )

    def test_native_error_codes_cross_transport_without_raw_exception_messages(self):
        adapter = MobileAdapter()
        for code in ('target_unavailable', 'app_not_ready', 'unknown_operation_error'):
            response = BytesIO(json.dumps({'error': True, 'cause': code}).encode())
            with patch('urllib.request.urlopen', return_value=response), self.assertRaises(Failure) as caught:
                adapter.user_step({'action': 'click', 'role': 'button', 'name': 'Save'})
            self.assertEqual(caught.exception.cause, code)

    def test_rollup_keeps_planned_denominator_and_overlapping_causes(self):
        result = {
            'diagnostics': diagnostics(
                [
                    issue(Failure(cause), phase='execution', operation='step', impact='zero_credit')
                    for cause in ('policy_violation', 'process_error', 'process_error')
                ]
            )
        }
        report = summarize([result], 3)
        self.assertEqual(report['planned_units'], 3)
        self.assertEqual(report['units_by_cause'], {'policy_violation': 1, 'process_error': 1})
        self.assertFalse(report['automatic_retries'])

    def test_lifecycle_failure_preserves_earlier_controller_diagnostic(self):
        from gui_agent_bench.trial import run_trial
        from gui_agent_bench.verifier.judge import write_result

        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)

            def fail(*args, **kwargs):
                write_result(
                    folder / 'logs/verifier',
                    status='trial_error',
                    diagnostics=diagnostics(
                        [
                            issue(
                                Failure('capability_unavailable'),
                                phase='setup',
                                operation='broker',
                                impact='zero_credit',
                            )
                        ]
                    ),
                )
                raise OSError('SECRET cleanup failure')

            with patch('gui_agent_bench.trial._run_trial', side_effect=fail):
                result = run_trial(folder, folder, folder)
            self.assertEqual(
                [x['cause'] for x in result['diagnostics']['issues']],
                ['capability_unavailable', 'infrastructure_error'],
            )
            self.assertEqual(result['reward'], 0)
            self.assertNotIn('SECRET', json.dumps(result))


@contextmanager
def provider_server(error):
    servers, ready = [], threading.Event()

    def bind(_address, handler):
        server = HTTPServer(('127.0.0.1', 0), handler)
        servers.append(server)
        ready.set()
        return server

    with (
        patch.object(gateway, 'HTTPServer', side_effect=bind),
        patch.dict('os.environ', {'OPENROUTER_API_KEY': 'TEST_SENTINEL'}),
        patch.object(gateway.urllib.request, 'urlopen', side_effect=error),
    ):
        thread = threading.Thread(target=gateway.serve, args=('openrouter', 'model'), daemon=True)
        thread.start()
        try:
            if not ready.wait(5):
                raise RuntimeError('provider fixture did not bind')
            yield servers[0].server_address
        finally:
            servers[0].shutdown()
            servers[0].server_close()
            thread.join(5)


class ProviderFailureTests(unittest.TestCase):
    def test_actual_relay_reports_distinct_provider_failures_safely(self):
        from http.client import HTTPConnection

        cases = [
            (urllib.error.HTTPError('http://private', 429, 'SECRET', {}, None), 'provider_rate_limit'),
            (urllib.error.HTTPError('http://private', 503, 'SECRET', {}, None), 'provider_error'),
            (TimeoutError('SECRET'), 'provider_timeout'),
            (urllib.error.URLError('SECRET'), 'provider_transport_error'),
        ]
        for error, cause in cases:
            output = StringIO()
            with self.subTest(cause=cause), redirect_stdout(output), provider_server(error) as address:
                connection = HTTPConnection(*address, timeout=3)
                connection.request(
                    'POST',
                    '/v1/chat/completions',
                    json.dumps({'model': 'model', 'messages': []}),
                    {'Content-Type': 'application/json'},
                )
                response = connection.getresponse()
                data = response.read().decode()
                connection.close()
            failures = [r['failure'] for r in map(json.loads, output.getvalue().splitlines()) if 'failure' in r]
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]['cause'], cause)
            self.assertNotIn('SECRET', data + output.getvalue())
            self.assertNotIn('TEST_SENTINEL', data + output.getvalue())


if __name__ == '__main__':
    unittest.main()
