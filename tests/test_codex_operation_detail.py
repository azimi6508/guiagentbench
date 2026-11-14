"""Fatal authoring diagnostics retain their originating trusted operation."""

import json
from pathlib import Path
import tempfile
import unittest
from gui_agent_bench.codex_audit import operation_failure
from gui_agent_bench.failures import Failure, public_error, issue
from gui_agent_bench.failure_detail import attach, detail


class OperationDetailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bridge = Path(self.temp.name) / 'bridge'
        self.bridge.mkdir()
        self.item = {
            'phase': 'completed',
            'tool': 'gui_step',
            'arguments': {'action': 'click', 'role': 'button', 'name': 'Apply'},
            'bridge_call_id': 'session:2',
            'result': {
                'isError': True,
                'content': [{'type': 'text', 'text': json.dumps(public_error(Failure('action_timeout')))}],
            },
        }
        origin = attach(
            TimeoutError('SECRET'),
            component='web_adapter',
            stage='target_action',
            facts={'target_matches': 0, 'browser_connected': True},
            elapsed_ms=30000,
        )
        self.failure = issue(origin, phase='authoring', operation='step', impact='feedback')
        self.row = {
            'tool': 'step',
            'arguments': self.item['arguments'],
            'operation_failed': True,
            'denied': False,
            'failure': self.failure,
        }

    def write(self, calls, rows):
        (self.bridge / 'bridge.ndjson').write_text(''.join(json.dumps(x) + '\n' for x in calls))
        # Docker-collected broker logs legitimately lack a trailing newline.
        (self.bridge.parent / 'browser.ndjson').write_text('\n'.join(json.dumps(x) for x in rows))

    def test_preserves_identity_and_observations_without_exposing_them_to_model(self):
        self.write([self.item], [self.row])
        error = operation_failure(self.item, self.bridge)
        self.assertEqual(detail(error), self.failure['detail'])
        self.assertEqual(public_error(error), public_error(Failure('action_timeout')))
        self.assertNotIn('SECRET', json.dumps(detail(error)))

    def test_repeated_arguments_are_correlated_by_occurrence_not_first_failure(self):
        first = {**self.item, 'bridge_call_id': 'session:1'}
        success = {k: v for k, v in self.row.items() if k != 'failure'}
        success['operation_failed'] = False
        self.write([first, self.item], [success, self.row])
        self.assertEqual(detail(operation_failure(self.item, self.bridge)), self.failure['detail'])
        self.assertIsNone(getattr(operation_failure(first, self.bridge), '_bench_failure_detail', None))

    def test_live_broker_detail_is_available_before_cleanup_exports_the_log(self):
        (self.bridge / 'bridge.ndjson').write_text(json.dumps(self.item) + '\n')
        self.assertFalse((self.bridge.parent / 'browser.ndjson').exists())
        error = operation_failure(self.item, self.bridge, lambda: json.dumps(self.row))
        self.assertEqual(detail(error), self.failure['detail'])
        self.assertFalse((self.bridge.parent / 'browser.ndjson').exists())

    def test_reconciliation_raises_original_operation_with_live_detail(self):
        from gui_agent_bench.codex_audit import reconcile

        started = {**self.item, 'phase': 'started'}
        completed = {**self.item, 'operation_failed': True, 'denied': False}
        self.write([started, completed], [])
        with self.assertRaises(Failure) as caught:
            reconcile(
                self.bridge.parent / 'agent',
                self.bridge,
                [{'name': 'gui_step'}],
                broker_log=lambda: json.dumps(self.row),
            )
        self.assertEqual(caught.exception.cause, 'action_timeout')
        self.assertEqual(detail(caught.exception), self.failure['detail'])

    def test_live_diagnostic_collection_failure_does_not_replace_operation_cause(self):
        self.write([self.item], [])

        def unavailable():
            raise RuntimeError('SECRET transport detail')

        error = operation_failure(self.item, self.bridge, unavailable)
        self.assertEqual(error.cause, 'action_timeout')
        self.assertIsNone(getattr(error, '_bench_failure_detail', None))

    def test_missing_ambiguous_mismatched_or_malformed_detail_never_changes_cause(self):
        bad_rows = [
            [],
            [self.row, self.row],
            [{**self.row, 'failure': {**self.failure, 'cause': 'device_unavailable'}}],
            [{**self.row, 'failure': {**self.failure, 'detail': {**self.failure['detail'], 'secret': 'SECRET'}}}],
        ]
        for rows in bad_rows:
            with self.subTest(rows=rows):
                self.write([self.item], rows)
                error = operation_failure(self.item, self.bridge)
                self.assertEqual(error.cause, 'action_timeout')
                self.assertIsNone(getattr(error, '_bench_failure_detail', None))


if __name__ == '__main__':
    unittest.main()
