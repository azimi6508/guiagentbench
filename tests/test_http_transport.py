"""Exercise real broker HTTP responses, including the empty MCP notification."""

from contextlib import closing, contextmanager, ExitStack
from http.client import HTTPConnection
from http.server import HTTPServer
import json
from pathlib import Path
import sys
import threading
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from gui_agent_bench import broker, oracle_broker


@contextmanager
def running_broker(module, mode='author', arm='test_ui', platform='web', adapter=None, viewport=(960, 640)):
    ready = threading.Event()
    servers, errors = [], []

    def bind(_address, handler):
        server = HTTPServer(('127.0.0.1', 0), handler)
        servers.append(server)
        ready.set()
        return server

    def run():
        try:
            if module is broker:
                module.serve(platform=platform, viewport=viewport)
            else:
                module.serve(
                    arm,
                    mode,
                    None,
                    platform=platform,
                    viewport=viewport,
                    reference_root=storage / 'author',
                    execution_references=storage / 'references',
                    evidence_root=storage / 'evidence',
                )
        except Exception as exc:
            errors.append(exc)
            ready.set()

    target = (
        'gui_agent_bench.adapters.factory.adapter_for'
        if module is broker
        else 'gui_agent_bench.oracle_broker.adapter_for'
    )
    with ExitStack() as stack:
        storage = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        from gui_agent_bench.visual import ReferenceStore

        ReferenceStore(storage / 'references', viewport)
        stack.enter_context(patch.object(module, 'HTTPServer', side_effect=bind))
        from test_visual import png

        adapter = adapter if adapter is not None else Mock()
        adapter.observe.return_value = png(size=viewport)
        if module is oracle_broker:
            stack.enter_context(patch.object(module, 'prepare'))
        stack.enter_context(patch(target, return_value=adapter))
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            if not ready.wait(5) or errors:
                raise RuntimeError('test broker did not bind', errors)
            yield servers[0].server_address
        finally:
            if servers:
                servers[0].shutdown()
                servers[0].server_close()
            thread.join(5)
            if thread.is_alive() or errors:
                raise RuntimeError('test broker did not shut down', errors)


class BrokerHTTPTests(unittest.TestCase):
    def test_idle_web_callbacks_progress_without_another_tool_request(self):
        for module in (broker, oracle_broker):
            adapter = Mock()
            pumped = threading.Event()
            adapter.page.wait_for_timeout.side_effect = lambda _: pumped.set()
            with self.subTest(module=module.__name__), running_broker(module, adapter=adapter):
                self.assertTrue(pumped.wait(2))
        for platform in ('mobile', 'tv'):
            adapter = Mock()
            with running_broker(broker, platform=platform, adapter=adapter) as address:
                self.exchange(address, 'GET', '/health')
            adapter.page.wait_for_timeout.assert_not_called()

    def test_only_author_can_capture_immutable_named_references(self):
        request = {
            'jsonrpc': '2.0',
            'id': 5,
            'method': 'tools/call',
            'params': {'name': 'observe', 'arguments': {'reference': 'chosen'}},
        }
        with running_broker(oracle_broker, arm='test_visual') as address:
            _, response = self.exchange(address, 'POST', '/mcp', request)
            self.assertFalse(response['result']['isError'])
            self.assertEqual(response['result']['content'][0]['type'], 'image')
            _, response = self.exchange(address, 'POST', '/mcp', request)
            self.assertTrue(response['result']['isError'])
            request['params']['arguments']['reference'] = '../escape'
            _, response = self.exchange(address, 'POST', '/mcp', request)
            self.assertTrue(response['result']['isError'])
        from test_visual import assertion

        with running_broker(oracle_broker, 'execute', 'test_visual') as address:
            for operation, arguments in [
                ('capture_reference', {'reference': 'new'}),
                ('assert', assertion(reference='missing')),
                ('assert', {'kind': 'pixels_text', 'precondition': False}),
                ('assert', {'kind': 'ui', 'precondition': False}),
                ('ui', {}),
            ]:
                self.assertEqual(
                    self.exchange(address, 'POST', '/call', {'operation': operation, 'arguments': arguments})[0], 400
                )

    def exchange(self, address, method, path, payload=None):
        body = json.dumps(payload) if payload is not None else None
        with closing(HTTPConnection(*address, timeout=3)) as connection:
            # Match OpenCode's request. The response must explicitly override
            # keep-alive even when it has a zero-length body (HTTP 202).
            connection.request(method, path, body, {'Connection': 'keep-alive', 'Content-Type': 'application/json'})
            response = connection.getresponse()
            self.assertEqual(response.getheader('Connection'), 'close')
            self.assertTrue(response.will_close)
            data = response.read()
            self.assertIsNone(connection.sock)
            return response.status, json.loads(data) if data else None

    def test_both_authoring_brokers_close_every_handshake_response(self):
        for module in [broker, oracle_broker]:
            with self.subTest(broker=module.__name__), running_broker(module) as address:
                status, health = self.exchange(address, 'GET', '/health')
                self.assertEqual((status, health['ready']), (200, True))
                request = {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {}}
                status, result = self.exchange(address, 'POST', '/mcp', request)
                self.assertEqual((status, result['id']), (200, 0))
                notification = {'jsonrpc': '2.0', 'method': 'notifications/initialized'}
                self.assertEqual(self.exchange(address, 'POST', '/mcp', notification), (202, None))
                self.assertEqual(self.exchange(address, 'GET', '/mcp')[0], 405)
                request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}
                status, result = self.exchange(address, 'POST', '/mcp', request)
                self.assertEqual((status, result['id']), (200, 1))
                self.assertEqual(
                    {t['name'] for t in result['result']['tools']}, {'observe', 'dump_ui', 'reset', 'open_url', 'step'}
                )

    def test_denials_also_close_connections(self):
        for module in [broker, oracle_broker]:
            with self.subTest(broker=module.__name__), running_broker(module) as address:
                self.assertEqual(self.exchange(address, 'GET', '/forbidden')[0], 405 if module is broker else 403)
                request = {
                    'jsonrpc': '2.0',
                    'id': 2,
                    'method': 'tools/call',
                    'params': {'name': 'shell', 'arguments': {}},
                }
                status, result = self.exchange(address, 'POST', '/mcp', request)
                self.assertEqual(status, 200)
                self.assertTrue(result['result']['isError'])

    def test_executor_keeps_its_boundary_and_closes_responses(self):
        with running_broker(oracle_broker, 'execute') as address:
            self.assertEqual(self.exchange(address, 'GET', '/health')[0], 200)
            self.assertEqual(self.exchange(address, 'POST', '/mcp', {'method': 'tools/list'})[0], 400)
            status, result = self.exchange(address, 'POST', '/call', {'operation': 'reset', 'arguments': {}})
            self.assertEqual((status, result), (200, {'value': None}))


if __name__ == '__main__':
    unittest.main()
