"""Slow application resets stay bounded by the task declaration and are never replayed."""

from contextlib import contextmanager
from unittest import TestCase
from unittest.mock import Mock, patch

from gui_agent_bench.adapters.web import WebAdapter
from gui_agent_bench.environment import web_preparation
from gui_agent_bench.failures import Failure


class WebResetDeadlineTests(TestCase):
    def adapter(self, reset_timeout):
        adapter = object.__new__(WebAdapter)
        adapter.profile = 'generic'
        adapter.preparation = web_preparation({} if reset_timeout is None else {'reset_timeout_sec': reset_timeout})
        adapter.base_url = 'http://app:8000'
        adapter.reset_generation = 0
        adapter._close_context = Mock()
        adapter._fresh_context = Mock()
        adapter.wait_ready = Mock()
        adapter.page = Mock()
        adapter.page.screenshot.return_value = b'png'
        adapter.context = Mock()
        adapter.context.storage_state.return_value = {}
        adapter.viewport = [1280, 720]
        adapter.timezone = 'UTC'
        return adapter

    def reset_after(self, reset_timeout, seconds):
        adapter = self.adapter(reset_timeout)
        elapsed = [0]
        requests = []

        @contextmanager
        def response(request, timeout):
            requests.append(request)
            elapsed[0] += min(seconds, timeout)
            if seconds > timeout:
                raise TimeoutError('Reset response deadline exceeded')
            yield Mock(status=200, headers={'X-GAB-Session': adapter.session})

        with (
            patch('gui_agent_bench.adapters.web.time.monotonic', side_effect=lambda: elapsed[0]),
            patch('gui_agent_bench.adapters.web.urllib.request.urlopen', side_effect=response),
            patch('gui_agent_bench.adapters.web.emit'),
        ):
            try:
                adapter.reset()
            except Failure as error:
                self.assertEqual(error.cause, 'reset_failure')
                self.assertEqual(len(requests), 1)
                adapter._fresh_context.assert_not_called()
                raise
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].method, 'POST')
        adapter._fresh_context.assert_called_once_with()
        adapter.page.goto.assert_called_once_with('http://app:8000/', wait_until='domcontentloaded')

    def test_declared_long_reset_completes_with_one_request(self):
        self.reset_after(60, 40)

    def test_declared_reset_still_times_out_without_replaying(self):
        with self.assertRaises(Failure):
            self.reset_after(60, 61)

    def test_default_reset_deadline_is_not_extended(self):
        for declared in (None, 30):
            with self.subTest(declared=declared), self.assertRaises(Failure):
                self.reset_after(declared, 40)

    def test_default_reset_completes_within_its_deadline(self):
        self.reset_after(None, 20)
