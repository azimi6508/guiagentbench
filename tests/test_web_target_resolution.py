import json
import unittest
from unittest.mock import Mock
from gui_agent_bench.adapters.web import WebAdapter
from gui_agent_bench.failures import Failure, issue, public_error, authoring_feedback, model_zero


class WebTargetResolutionTests(unittest.TestCase):
    def test_absent_target_does_not_dispatch_and_is_authoring_feedback_only(self):
        a = object.__new__(WebAdapter)
        a.wait_ready = Mock()
        a._playwright_timeout_error = TimeoutError
        t = Mock()
        t.count.return_value = 0
        t.wait_for.side_effect = TimeoutError('Not attached')
        for action in ('click', 'fill', 'hover', 'press'):
            with self.assertRaises(Failure) as c:
                a._user_step({'action': action, 'role': 'button', 'text': 'x', 'key': 'Enter'}, t)
            result = {'isError': True, 'content': [{'type': 'text', 'text': json.dumps(public_error(c.exception))}]}
            self.assertEqual(authoring_feedback(result, 'gui_step'), 'target_unavailable')
            diagnostic = issue(c.exception, phase='execution', operation='step', impact='zero_credit')
            self.assertFalse(model_zero([diagnostic]))
            self.assertFalse(diagnostic['detail']['facts']['action_dispatched'])
        for operation in ('click', 'fill', 'hover', 'press'):
            getattr(t, operation).assert_not_called()
        a.wait_ready.assert_not_called()

    def test_loading_target_keeps_bounded_resolution_wait_before_single_dispatch(self):
        a = object.__new__(WebAdapter)
        a.wait_ready = Mock()
        a._playwright_timeout_error = TimeoutError
        t = Mock()
        t.count.side_effect = [0, 1]
        a._user_step({'action': 'click', 'role': 'button'}, t)
        t.wait_for.assert_called_once_with(state='attached')
        t.click.assert_called_once()

    def test_dispatched_timeout_is_not_reinterpreted_or_retried(self):
        a = object.__new__(WebAdapter)
        t = Mock()
        t.count.return_value = 1
        original = TimeoutError('PRIVATE')
        t.click.side_effect = original
        with self.assertRaises(TimeoutError) as c:
            a._user_step({'action': 'click', 'role': 'button'}, t)
        self.assertIs(c.exception, original)
        t.click.assert_called_once()

    def test_hit_test_probe_failure_keeps_original_diagnostic(self):
        a = object.__new__(WebAdapter)
        a.page = Mock()
        a.page.is_closed.return_value = False
        a.browser = Mock()
        a.browser.is_connected.return_value = True
        t = Mock()
        t.count.return_value = 1
        t.is_visible.return_value = True
        t.is_enabled.return_value = True
        t.evaluate.side_effect = RuntimeError('PRIVATE DOM')
        import time

        e = TimeoutError('PRIVATE TIMEOUT')
        a.diagnose_target(e, t, time.monotonic())
        result = issue(e, phase='execution', operation='step', impact='zero_credit')
        self.assertEqual(result['cause'], 'action_timeout')
        self.assertTrue(result['detail']['facts']['probe_failed'])
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(set(public_error(e)), {'cause', 'message'})


if __name__ == '__main__':
    unittest.main()
