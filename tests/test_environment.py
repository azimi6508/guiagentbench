"""Readiness and reset failure behavior independent of application labels."""

import contextlib
import io
from pathlib import Path
import unittest
import urllib.error
from unittest.mock import Mock, patch

from gui_agent_bench.adapters.web import WebAdapter
from gui_agent_bench.environment import preparation_for, profile_for, web_preparation
from gui_agent_bench.failures import Failure


class EnvironmentTests(unittest.TestCase):
    def adapter(self):
        adapter = object.__new__(WebAdapter)
        adapter.profile, adapter.base_url = 'generic', 'http://app:8000'
        adapter.preparation = web_preparation()
        adapter.context, adapter.page = Mock(), Mock()
        adapter.pending, adapter.reset_generation = set(), 0
        adapter._playwright_timeout_error = TimeoutError
        return adapter

    def test_initial_timeout_is_explicit(self):
        a = self.adapter()
        a.page.wait_for_load_state.side_effect = TimeoutError()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(Failure) as caught:
            a.wait_ready(initial=True)
        self.assertEqual(caught.exception.cause, 'app_not_ready')

    def test_landmarks_only_gate_initial_preparation(self):
        a = self.adapter()
        a.preparation = web_preparation({'ready': [{'role': 'button', 'name': 'Emoji'}]})
        with contextlib.redirect_stdout(io.StringIO()):
            a.wait_ready(initial=True)
        a.page.get_by_role.assert_called_once_with('button', name='Emoji', exact=True)
        a.page.reset_mock()
        a.wait_ready()
        a.page.get_by_role.assert_not_called()
        a.page.wait_for_timeout.assert_called_once_with(250)

    def test_font_preparation_is_initial_only_and_keeps_existing_deadline(self):
        a = self.adapter()
        a.preparation = web_preparation({'wait_for_fonts': True})
        with contextlib.redirect_stdout(io.StringIO()):
            a.wait_ready(initial=True)
        call = a.page.wait_for_function.call_args
        self.assertEqual(call.args, ("document.fonts.status === 'loaded'",))
        self.assertGreater(call.kwargs['timeout'], 0)
        self.assertLessEqual(call.kwargs['timeout'], 10000)
        a.page.reset_mock()
        a.wait_ready()
        a.observe()
        a.dump_ui()
        a.page.wait_for_function.assert_not_called()

    def test_font_preparation_timeout_is_setup_failure(self):
        a = self.adapter()
        a.preparation = web_preparation({'wait_for_fonts': True})
        a.page.wait_for_function.side_effect = TimeoutError()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(Failure) as caught:
            a.wait_ready(initial=True)
        self.assertEqual(caught.exception.cause, 'app_not_ready')

    def test_observations_do_not_wait_for_global_readiness(self):
        a = self.adapter()
        a.wait_ready = Mock(side_effect=AssertionError('must remain observable'))
        a.observe()
        a.dump_ui()
        a.wait_ready.assert_not_called()
        a.page.screenshot.assert_called_once_with(type='png')

    def test_unknown_initial_error_remains_error(self):
        a = self.adapter()
        a.page.wait_for_load_state.side_effect = RuntimeError('private detail')
        with contextlib.redirect_stdout(io.StringIO()) as log, self.assertRaises(RuntimeError):
            a.wait_ready(initial=True)
        self.assertIn('"status": "error"', log.getvalue())
        self.assertNotIn('private detail', log.getvalue())

    def test_failed_reset_closes_old_context_and_never_retries_http_failure(self):
        a = self.adapter()
        old_context = a.context

        def request(*args, **kwargs):
            old_context.close.assert_called_once()
            self.assertIsNone(a.page)
            raise urllib.error.HTTPError(a.base_url, 503, 'not ready', {}, None)

        with (
            patch('urllib.request.urlopen', side_effect=request) as call,
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(Failure) as caught,
        ):
            a.reset()
        self.assertEqual(caught.exception.cause, 'reset_failure')
        self.assertEqual(call.call_count, 1)
        with self.assertRaises(Failure):
            a.observe()

    def test_declared_reset_deadlines_do_not_retry_lost_responses(self):
        # Slow applications declare their own bounded reset window.
        for declared, expected_timeout in [({'reset_timeout_sec': 60}, 60), ({}, 30)]:
            with self.subTest(declared=declared):
                adapter = self.adapter()
                adapter.preparation = web_preparation(declared)
                response = Mock(status=200, headers={})
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                with (
                    patch('urllib.request.urlopen', return_value=response) as call,
                    patch('time.monotonic', return_value=0),
                    contextlib.redirect_stdout(io.StringIO()),
                    self.assertRaises(Failure),
                ):
                    adapter.reset()
                self.assertEqual(call.call_args.kwargs['timeout'], expected_timeout)
                self.assertEqual(call.call_count, 1)

    def test_reset_requires_session_acknowledgement(self):
        a = self.adapter()
        response = Mock(status=200, headers={})
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with (
            patch('urllib.request.urlopen', return_value=response),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(Failure) as caught,
        ):
            a.reset()
        self.assertEqual(caught.exception.cause, 'reset_failure')
        self.assertIsNone(a.context)

    def test_tasks_declare_their_own_initial_landmarks(self):
        example = Path(__file__).resolve().parents[1] / 'tasks/web/webarena-399-profile-bio'
        self.assertEqual(profile_for(example, 'web'), 'generic')
        self.assertEqual(
            preparation_for(example)['ready'],
            [{'role': 'heading', 'name': 'MarvelsGrantMan136'}, {'role': 'link', 'name': 'Edit biography'}],
        )
        self.assertEqual(preparation_for(example)['reset_timeout_sec'], 150)
        self.assertEqual(profile_for(Path('any'), 'mobile'), 'mobile')
        self.assertEqual(profile_for(Path('unregistered'), 'web'), 'generic')

    def test_web_preparation_declarations_are_validated(self):
        self.assertEqual(
            web_preparation(), {'ready': [], 'fixed_clock': None, 'wait_for_fonts': False, 'reset_timeout_sec': 30}
        )
        for invalid in (
            {'ready': [{'role': 'button'}]},
            {'ready': [{'role': 'not-a-role', 'name': 'x'}]},
            {'fixed_clock': '2026-10-12T18:00:00'},
            {'wait_for_fonts': 'yes'},
            {'reset_timeout_sec': 0},
            {'unknown': True},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                web_preparation(invalid)
