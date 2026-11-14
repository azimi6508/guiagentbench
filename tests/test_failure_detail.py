"""Failure evidence survives boundaries without becoming a label or side channel."""

from io import BytesIO
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from gui_agent_bench.failure_detail import detail, native_result, validate
from gui_agent_bench.failures import Failure, explain, issue, public_error, model_zero
from gui_agent_bench.adapters.mobile import MobileAdapter
from gui_agent_bench.adapters.web import WebAdapter
from gui_agent_bench.run_plan import health
from gui_agent_bench.verifier.oracle import classify, pair_result


class FailureDetailTests(unittest.TestCase):

    def test_identity_survives_native_transport_and_wrapping_but_is_not_public(self):
        error = subprocess.CalledProcessError(7, ['SECRET_COMMAND'], output=b'SECRET_OUTPUT', stderr=b'SECRET_KEY')
        response, driver = native_result(error, component='native_driver', correlation_id='a' * 32, elapsed_ms=12)
        adapter = MobileAdapter()
        with patch('urllib.request.urlopen', return_value=BytesIO(json.dumps(response).encode())):
            try:
                adapter.user_step({'action': 'click', 'role': 'button', 'name': 'Save'})
            except Failure as remote:
                recorded = issue(remote, phase='execution', operation='step', impact='zero_credit')
                wrapped = Failure('reset_failure')
                wrapped.__cause__ = remote
                wrapped_record = issue(wrapped, phase='setup', operation='reset', impact='zero_credit')
                public = public_error(remote)
            else:
                self.fail('Expected remote error')
        self.assertEqual(recorded['detail'], driver['detail'])
        self.assertEqual(wrapped_record['detail']['failure_id'], driver['detail']['failure_id'])
        self.assertEqual(recorded['detail']['facts']['process_returncode'], 7)
        self.assertEqual(recorded['detail']['correlation_id'], 'a' * 32)
        self.assertEqual(set(public), {'cause', 'message'})
        self.assertNotIn(driver['detail']['failure_id'], json.dumps(public))
        self.assertNotIn('SECRET', json.dumps([driver, recorded, wrapped_record, public]))

    def test_unknown_errors_have_code_locations_without_raw_exception_or_locals(self):
        adapter = object.__new__(WebAdapter)
        adapter.context, adapter.page, adapter.browser = (Mock(), Mock(), Mock())
        adapter.page.is_closed.return_value = False
        adapter.browser.is_connected.return_value = True
        target = adapter.page.get_by_role.return_value
        target.count.return_value = 1
        target.is_visible.return_value = True
        target.is_enabled.return_value = False
        target.click.side_effect = RuntimeError('SECRET URL?token=SECRET')
        try:
            adapter.user_step({'action': 'click', 'role': 'button', 'name': 'SECRET_LABEL'})
        except RuntimeError as exc:
            recorded = issue(exc, phase='execution', operation='step', impact='zero_credit')
        else:
            self.fail('Expected exception')
        self.assertEqual(recorded['cause'], 'unknown_operation_error')
        self.assertFalse(model_zero([recorded]))
        self.assertTrue(any((f['file'] == 'adapters/web.py' for f in recorded['detail']['frames'])))
        self.assertEqual(recorded['detail']['facts']['enabled'], False)
        self.assertEqual(recorded['detail']['facts']['observation'], 'after_failure')
        self.assertIn('exact matches observed: 1', explain([recorded]))
        self.assertNotIn('SECRET', json.dumps(recorded))
        target.click.assert_called_once()

    def test_failed_diagnostic_probe_preserves_original_error_and_zero_credit(self):
        adapter = object.__new__(WebAdapter)
        adapter.context, adapter.page, adapter.browser = (Mock(), Mock(), Mock())
        adapter.page.is_closed.side_effect = RuntimeError('diagnosis unavailable')
        target = adapter.page.get_by_role.return_value
        target.count.return_value = 1
        original = TimeoutError('SECRET')
        target.click.side_effect = original
        with self.assertRaises(TimeoutError) as caught:
            adapter.user_step({'action': 'click', 'role': 'button', 'name': 'Save'})
        self.assertIs(caught.exception, original)
        recorded = issue(original, phase='execution', operation='step', impact='zero_credit')
        self.assertTrue(recorded['detail']['facts']['probe_failed'])
        result = classify([{'operation_failed': True, 'failure': recorded}], 0)
        self.assertEqual(pair_result([result, result])['reward'], 0)
        target.click.assert_called_once()

    def test_locator_construction_error_is_not_repeated_during_diagnosis(self):
        adapter = object.__new__(WebAdapter)
        adapter.context, adapter.page, adapter.browser = (Mock(), Mock(), Mock())
        original = RuntimeError('SECRET locator failure')
        adapter.page.get_by_role.side_effect = original
        with self.assertRaises(RuntimeError) as caught:
            adapter.user_step({'action': 'click', 'role': 'button', 'name': 'Save'})
        self.assertIs(caught.exception, original)
        adapter.page.get_by_role.assert_called_once()

    def test_extra_or_private_transport_detail_is_rejected_without_echo(self):
        good = detail(Failure('target_unavailable'))
        for bad in (
            {**good, 'traceback': 'SECRET'},
            {**good, 'facts': {'url': 'SECRET'}},
            {**good, 'frames': [{'file': '../../private/gold.py', 'line': 1}]},
            {**good, 'component': 'SECRET'},
            {**good, 'failure_id': 11111111111111111111111111111111},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate(bad)
            response = {'error': True, 'cause': 'target_unavailable', 'detail': bad}
            with (
                patch('urllib.request.urlopen', return_value=BytesIO(json.dumps(response).encode())),
                self.assertRaises(Failure) as caught,
            ):
                MobileAdapter().call('ui')
            recorded = issue(caught.exception, phase='execution', operation='ui', impact='zero_credit')
            self.assertEqual(recorded['cause'], 'infrastructure_error')
            self.assertFalse(recorded['detail']['facts']['diagnostic_valid'])
            self.assertNotIn('SECRET', json.dumps(recorded))

    def test_run_health_retains_cooccurring_failures_instead_of_only_infrastructure(self):
        first = issue(Failure('device_unavailable'), phase='execution', operation='step', impact='zero_credit')
        second = issue(Failure('policy_violation'), phase='execution', operation='ui', impact='zero_credit')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'trials/one/logs/verifier/metrics.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'diagnostics': {'issues': [first, second]}}))
            result = health(root, {'status': 'complete', 'invalid_or_missing': 1}, 'codex/gpt-6-luna')
        self.assertTrue(result['errors'])
        self.assertEqual(result['diagnostics']['issues'], [first, second])
        self.assertIn('device_unavailable', result['error'])
        self.assertIn('policy_violation', result['error'])

    def test_historical_errors_do_not_acquire_invented_observations(self):
        old = {'cause': 'unknown_operation_error', 'impact': 'zero_credit'}
        self.assertNotIn('Observed:', explain([old]))
        self.assertNotIn('detail', old)

    def test_reconstructed_verifier_deductions_are_identical_across_replays(self):
        from test_oracle import record

        ledger = [record('setup', True, True), record('behavior', False)]
        first, second = (classify(ledger, 0), classify(ledger, 0))
        self.assertEqual(first, second)
        self.assertNotIn('detail', first['diagnostics']['issues'][0])
        crash = classify([], 1, 'TIMEOUT', termination_causes=['TIMEOUT'])
        self.assertEqual(crash, classify([], 1, 'TIMEOUT', termination_causes=['TIMEOUT']))

    def test_validation_wrapper_retains_the_originating_contract_location(self):
        from gui_agent_bench.failures import checked
        from gui_agent_bench.actions import validate_step

        try:
            checked(
                validate_step,
                {'action': 'click', 'x': 'SECRET_INVALID_COORDINATE', 'y': 200},
                (960, 640),
                ui=True,
                platform='web',
            )
        except Failure as exc:
            recorded = issue(exc, phase='authoring', operation='step', impact='feedback')
        else:
            self.fail('Invalid action accepted')
        self.assertEqual(recorded['cause'], 'invalid_arguments')
        self.assertTrue(any((f['file'] == 'actions.py' for f in recorded['detail']['frames'])))
        self.assertNotIn('SECRET', json.dumps(recorded))


if __name__ == '__main__':
    unittest.main()
