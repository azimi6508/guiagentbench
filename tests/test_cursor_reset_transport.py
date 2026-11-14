import json
import unittest
from unittest.mock import patch

from gui_agent_bench.codex_bridge import Broker


class PreparedResetTransportTests(unittest.TestCase):
    def broker(self, arm, platform, profile='generic'):
        value = Broker.__new__(Broker)

        # Exercise constructor policy and its ordinary startup exchanges too.
        def reply(connection, method, path, body, headers):
            connection.value = json.loads(body)

        class Connection:
            def __init__(self, host, port, timeout):
                self.timeout = timeout

            request = reply

            def getresponse(self):
                request = self.value
                reset = request.get('params', {}).get('name') == 'reset'
                if reset and self.timeout < 90:
                    raise TimeoutError('synthetic prepared journey exceeds60 seconds')
                result = {'tools': []} if request['method'] == 'tools/list' else {'ready': True}
                if request['method'].startswith('notifications/'):
                    status, raw = 202, b''
                else:
                    status, raw = 200, json.dumps({'id': request['id'], 'result': result}).encode()
                return type('Response', (), {'status': status, 'read': lambda self, limit: raw})()

            def close(self):
                pass

        self.addCleanup(patch.stopall)
        self.factory = patch('gui_agent_bench.codex_bridge.http.client.HTTPConnection', side_effect=Connection).start()
        Broker.__init__(value, [], arm=arm, platform=platform, profile=profile)
        self.factory.reset_mock()
        return value

    def test_native_oracle_prepared_reset_completes_once(self):
        for arm in ('oracle_visual', 'oracle_ui'):
            with self.subTest(arm=arm):
                broker = self.broker(arm, 'mobile', 'native_extended')
                self.assertEqual(broker.request('tools/call', {'name': 'reset', 'arguments': {}}), {'ready': True})
                self.assertEqual(self.factory.call_count, 1)

    def test_other_reset_scopes_keep_single_operation_timeout(self):
        for arm, platform, profile in [
            ('test_ui', 'mobile', 'native_extended'),
            ('test_visual', 'mobile', 'native_extended'),
            ('judge_test', 'mobile', 'native_extended'),
            ('oracle_visual', 'web', 'generic'),
            ('oracle_ui', 'web', 'generic'),
            ('oracle_visual', 'tv', 'generic'),
            ('oracle_visual', 'mobile', 'generic'),
            ('oracle_ui', 'mobile', 'generic'),
        ]:
            with self.subTest(arm=arm, platform=platform, profile=profile):
                broker = self.broker(arm, platform, profile)
                with self.assertRaises(TimeoutError):
                    broker.request('tools/call', {'name': 'reset', 'arguments': {}})
                self.assertEqual(self.factory.call_count, 1)

    def test_native_non_reset_calls_keep_ordinary_timeout(self):
        broker = self.broker('oracle_visual', 'mobile', 'native_extended')
        broker.request('tools/call', {'name': 'observe', 'arguments': {}})
        self.assertEqual(self.factory.call_args.kwargs['timeout'], 60)

    def test_reset_completion_does_not_retry_failed_response(self):
        broker = self.broker('oracle_visual', 'mobile', 'native_extended')
        self.factory.side_effect = TimeoutError('synthetic transport failure')
        with self.assertRaises(TimeoutError):
            broker.request('tools/call', {'name': 'reset', 'arguments': {}})
        self.assertEqual(self.factory.call_count, 1)
