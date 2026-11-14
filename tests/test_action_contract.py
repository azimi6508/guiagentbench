"""Public examples checked against schemas, validation and real HTTP dispatch."""

import unittest
from pathlib import Path
from unittest.mock import Mock, call

from test_http_transport import running_broker
import test_http_transport
from gui_agent_bench import broker, oracle_broker
from gui_agent_bench.actions import validate_step, execute_step


VISUAL = [
    dict(action='click', x=120, y=200),
    dict(action='hover', x=120, y=200),
    dict(action='scroll', dx=0, dy=100),
    dict(action='type', text='hello'),
    dict(action='press', key='Tab'),
    dict(action='reload'),
]
TARGETED = [
    dict(action='click', role='button', name='Save'),
    dict(action='hover', role='button', name='Save'),
    dict(action='fill', role='textbox', name='Editor', text='hello'),
    dict(action='press', role='textbox', name='Editor', key='Enter'),
]
BAD = [
    dict(action='click', x=True, y=200),
    dict(action='click', x=960, y=200),
    dict(action='click', x=2, y=200, role='button', name='Save'),
    dict(action='click', name='Save'),
    dict(action='fill', text='hello'),
    dict(action='type', text='x', selector='#editor'),
    dict(action='press', key='F12'),
    dict(action='scroll', dx=0, dy=2001),
    dict(action='evaluate', code='1+1'),
]


class ActionContractTests(unittest.TestCase):
    exchange = test_http_transport.BrokerHTTPTests.exchange

    def test_schema_and_validator_agree_on_examples(self):
        for platform in ('web', 'mobile'):
            for arm in ('oracle_visual', 'oracle_ui', 'test_visual', 'test_ui'):
                tools = broker.platform_tools(oracle_broker.tools_for(arm), platform)
                schema = next(t['inputSchema'] for t in tools if t['name'] == 'step')
                ui = arm.endswith('_ui')
                for args in VISUAL + (TARGETED if ui else []):
                    with self.subTest(platform=platform, arm=arm, args=args):
                        if platform == 'mobile' and args['action'] == 'hover':
                            self.assertNotIn('hover', schema['properties']['action']['enum'])
                            with self.assertRaises(ValueError):
                                validate_step(args, (960, 640), ui=ui, platform=platform)
                        else:
                            self.assertIn(args['action'], schema['properties']['action']['enum'])
                            self.assertTrue(set(args) <= set(schema['properties']))
                            validate_step(args, (960, 640), ui=ui, platform=platform)

    def test_denied_actions_have_no_adapter_side_effects(self):
        for platform in ('web', 'mobile'):
            for ui in (False, True):
                denied = BAD + ([] if ui else TARGETED)
                if platform == 'mobile':
                    denied += [
                        dict(action='click', x=10, y=127),
                        dict(action='click', x=10, y=1244),
                        dict(action='hover', x=10, y=200),
                    ]
                for args in denied:
                    adapter = Mock()
                    with self.subTest(platform=platform, ui=ui, args=args), self.assertRaises(ValueError):
                        execute_step(adapter, args, (960, 1280), ui=ui, platform=platform)
                    self.assertEqual(adapter.mock_calls, [])

    def test_authoring_dispatches_both_targeting_forms(self):
        for platform in ('web', 'mobile'):
            for module, arm in ((broker, 'judge_test'), (oracle_broker, 'oracle_ui'), (oracle_broker, 'test_ui')):
                adapter = Mock()
                with (
                    self.subTest(platform=platform, arm=arm),
                    running_broker(module, arm=arm, platform=platform, adapter=adapter) as address,
                ):
                    for args in VISUAL + TARGETED:
                        if platform == 'mobile' and args['action'] == 'hover':
                            continue
                        _, response = self.exchange(
                            address,
                            'POST',
                            '/mcp',
                            {
                                'jsonrpc': '2.0',
                                'id': 1,
                                'method': 'tools/call',
                                'params': {'name': 'step', 'arguments': args},
                            },
                        )
                        self.assertFalse(response['result']['isError'], args)
                    adapter.user_step.assert_any_call(TARGETED[0])
                    if platform == 'mobile':
                        adapter.visual_step.assert_any_call(VISUAL[0])
                    else:
                        adapter.page.mouse.click.assert_called_with(120, 200)
                        adapter.page.keyboard.insert_text.assert_called_with('hello')

    def test_execution_dispatch_and_denials_through_http(self):
        for platform in ('web', 'mobile'):
            for arm in ('test_visual', 'test_ui', 'oracle_visual', 'oracle_ui'):
                adapter = Mock()
                with (
                    self.subTest(platform=platform, arm=arm),
                    running_broker(oracle_broker, 'execute', arm, platform, adapter) as address,
                ):
                    for args in VISUAL + TARGETED + BAD:
                        allowed = (
                            arm.startswith('test_')
                            and args not in BAD
                            and (args in VISUAL or arm.endswith('_ui'))
                            and not (platform == 'mobile' and args['action'] == 'hover')
                        )
                        adapter.reset_mock()
                        status, _ = self.exchange(address, 'POST', '/call', {'operation': 'step', 'arguments': args})
                        self.assertEqual(status, 200 if allowed else 400, (arm, args))
                        if not allowed:
                            # Idle browser event processing is independent of the
                            # denied request; every other adapter effect is forbidden.
                            effects = [item for item in adapter.mock_calls if item != call.page.wait_for_timeout(1)]
                            self.assertEqual(effects, [])

    def test_tv_does_not_inherit_touch_or_ui_actions(self):
        tools = broker.platform_tools(oracle_broker.tools_for('test_visual'), 'tv')
        self.assertNotIn('dump_ui', {t['name'] for t in tools})
        schema = next(t['inputSchema'] for t in tools if t['name'] == 'step')
        self.assertNotIn('x', schema['properties'])
        self.assertNotIn('role', schema['properties'])
        for arm in ('oracle_ui', 'test_ui'):
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                oracle_broker.serve(arm, 'author', None, platform='tv')

    def test_downstream_authoring_caps_never_bind_before_the_agent_step_limit(self):
        import tempfile
        from gui_agent_bench import budgets
        from gui_agent_bench.runners.opencode import configuration

        root = Path(__file__).resolve().parents[1]
        for arm in ('judge_visual', 'judge_test', 'oracle_visual', 'oracle_ui', 'test_visual', 'test_ui'):
            with self.subTest(arm=arm), tempfile.TemporaryDirectory() as folder:
                config = configuration(root, Path(folder) / 'opencode.json', 'relay', 'model', arm)
                steps = config['agent']['bench']['steps']
                self.assertEqual(steps, budgets.agent_steps(arm))
                self.assertGreater(budgets.provider_requests(arm), steps)
                self.assertGreaterEqual(budgets.author_tool_calls(arm), steps)
                self.assertGreaterEqual(budgets.author_broker_posts(arm), 2 * budgets.author_tool_calls(arm))
        self.assertGreaterEqual(budgets.DEFAULT_TIMEOUT_SECONDS, 200 * 15)
        budgets.check_timeout(budgets.MAX_TIMEOUT_SECONDS)
        with self.assertRaises(ValueError):
            budgets.check_timeout(budgets.MAX_TIMEOUT_SECONDS + 1)

    def test_qualification_fixtures_fit_real_cli_and_agent_budgets(self):
        from gui_agent_bench.cli import parser
        from gui_agent_bench.gateway import fixture_reply
        from gui_agent_bench.budgets import agent_steps

        for platform, control in [('web', 'profile-bio'), ('mobile', 'markor')]:
            for arm in ('judge_test', 'oracle_ui', 'test_ui'):
                parser().parse_args(
                    [
                        '_gateway',
                        '--provider',
                        'fixture',
                        '--model',
                        'scripted',
                        '--fixture-oracle',
                        control,
                        '--arm',
                        arm,
                        '--platform',
                        platform,
                    ]
                )
                messages = []
                for _ in range(agent_steps(arm)):
                    message, reason = fixture_reply(messages, 'PASS', True, arm, control, platform)
                    messages.append(message)
                    if reason == 'stop':
                        break
                self.assertEqual(reason, 'stop', (platform, arm))
                self.assertEqual(messages[-2]['tool_calls'][0]['function']['name'], 'write')


if __name__ == '__main__':
    unittest.main()
