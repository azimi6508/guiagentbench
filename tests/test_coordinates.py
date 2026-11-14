"""Geometry stays explicit across public images, instructions and mouse dispatch."""

import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import test_http_transport
from test_http_transport import running_broker
from test_visual import png
from gui_agent_bench import broker, oracle_broker
from gui_agent_bench.coordinates import observation_content
from gui_agent_bench.materialize import materialize

ROOT = Path(__file__).resolve().parents[1]


class CoordinateContractTests(unittest.TestCase):
    exchange = test_http_transport.BrokerHTTPTests.exchange

    def test_both_brokers_publish_actual_geometry_and_unchanged_pixels(self):
        cases = [('web', (960, 640)), ('web', (1280, 800)), ('mobile', (720, 1280)), ('tv', (960, 540))]
        for platform, viewport in cases:
            for module in (broker, oracle_broker):
                with self.subTest(platform=platform, viewport=viewport, module=module.__name__):
                    with running_broker(module, arm='test_visual', platform=platform, viewport=viewport) as address:
                        request = {
                            'jsonrpc': '2.0',
                            'id': 1,
                            'method': 'tools/call',
                            'params': {'name': 'observe', 'arguments': {}},
                        }
                        _, response = self.exchange(address, 'POST', '/mcp', request)
                        self.assertFalse(response['result']['isError'])
                        image, description = response['result']['content']
                        self.assertEqual(base64.b64decode(image['data']), png(size=viewport))
                        metadata = json.loads(description['text'].split('\n', 1)[0].split(': ', 1)[1])
                        self.assertEqual(
                            metadata,
                            {
                                'width': viewport[0],
                                'height': viewport[1],
                                'units': 'pixels',
                                'coordinate_space': 'original_screenshot',
                                'origin': [0, 0],
                                'x_axis': 'right',
                                'y_axis': 'down',
                            },
                        )
                        self.assertIn('0 <= x < ' + str(viewport[0]), description['text'])
                        self.assertIn('0 <= y < ' + str(viewport[1]), description['text'])
                        request['method'] = 'tools/list'
                        del request['params']
                        _, response = self.exchange(address, 'POST', '/mcp', request)
                        expected = oracle_broker.tools_for('test_visual') if module is oracle_broker else broker.TOOLS
                        self.assertEqual(response['result'], {'tools': broker.platform_tools(expected, platform)})
                        tools = {t['name']: t for t in response['result']['tools']}
                        for name in ('observe', 'step'):
                            if platform != 'tv' or name == 'observe':
                                self.assertIn('screenshot width and height', tools[name]['description'])
                                self.assertIn('top-left origin (0, 0)', tools[name]['description'])
                        if platform == 'tv':
                            self.assertNotIn('x', tools['step']['inputSchema']['properties'])
                            self.assertIn('remote keys, not pointer actions', description['text'])
                        elif platform == 'mobile':
                            self.assertNotIn('hover', tools['step']['inputSchema']['properties']['action']['enum'])

    def test_mismatched_image_cannot_publish_misleading_action_geometry(self):
        with self.assertRaisesRegex(ValueError, 'action viewport'):
            observation_content(png(size=(960, 640)), (1280, 800), 'web')

    def test_authoring_and_execution_deliver_identical_unscaled_pixel_clicks(self):
        for module, mode in ((broker, 'author'), (oracle_broker, 'author'), (oracle_broker, 'execute')):
            adapter = Mock()
            with self.subTest(module=module.__name__, mode=mode):
                with running_broker(module, mode, 'test_visual', adapter=adapter) as address:
                    for x, y in ((187, 350), (195, 546), (959, 639)):
                        args = {'action': 'click', 'x': x, 'y': y}
                        if mode == 'author':
                            payload = {
                                'jsonrpc': '2.0',
                                'id': 1,
                                'method': 'tools/call',
                                'params': {'name': 'step', 'arguments': args},
                            }
                            status, response = self.exchange(address, 'POST', '/mcp', payload)
                            self.assertFalse(response['result']['isError'])
                        else:
                            status, _ = self.exchange(
                                address, 'POST', '/call', {'operation': 'step', 'arguments': args}
                            )
                        self.assertEqual(status, 200)
                        adapter.page.mouse.click.assert_called_with(x, y)

    def test_instructions_use_public_runtime_dimensions_for_every_live_arm(self):
        cases = [
            ('web/webarena-399-profile-bio', 'web', (960, 640)),
            ('tv/aura-013-caption-preview-size', 'web', (1280, 720)),
            ('mobile/markor-note-persistence', 'mobile', (720, 1280)),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            evidence = folder / 'evidence'
            evidence.mkdir()
            (evidence / 'steps.json').write_text('[]')
            for task_id, platform, viewport in cases:
                arms = ['judge_test', 'oracle_visual', 'test_visual']
                if platform != 'tv':
                    arms += ['oracle_ui', 'test_ui']
                for arm in arms:
                    with self.subTest(task=task_id, arm=arm):
                        workspace = folder / (task_id.replace('/', '-') + '-' + arm)
                        materialize(
                            ROOT, ROOT / 'tasks' / task_id, evidence, workspace, arm, platform, viewport=viewport
                        )
                        text = (workspace / 'instruction.md').read_text()
                        self.assertIn(f'width={viewport[0]} pixels, height={viewport[1]} pixels', text)
                        self.assertIn('top-left origin (0, 0)', text)
                        self.assertIn('x increases right and y increases down', text)
                        self.assertIn('not percentages or a normalized 0-1000 scale', text)


if __name__ == '__main__':
    unittest.main()
