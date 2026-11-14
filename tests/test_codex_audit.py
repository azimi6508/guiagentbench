import base64
import json
from pathlib import Path
import tempfile
import unittest

from gui_agent_bench.codex_audit import reconcile
from gui_agent_bench.codex_bridge import META, catalog
from gui_agent_bench.runners.registry import canonical
from gui_agent_bench.viewer.codex import envelope, identity, presentation


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.agent = self.root / 'agent'
        self.bridge = self.root / 'bridge'
        self.agent.mkdir()
        self.bridge.mkdir()
        self.result = {'content': [{'type': 'text', 'text': '[]'}], 'isError': False, '_meta': {META: 'session:1'}}
        common = {'bridge_call_id': 'session:1', 'mcp_request_id': 7, 'tool': 'bench_list_files', 'arguments': {}}
        self.ledger = [
            dict(common, phase='started'),
            dict(common, phase='completed', result=self.result, operation_failed=False),
        ]
        tool = {'type': 'mcpToolCall', 'id': 'item', 'server': 'bench', 'tool': 'bench_list_files', 'arguments': {}}
        self.events = [
            {'method': 'hook/started', 'params': {'run': {'id': 'hook'}}},
            {
                'method': 'hook/completed',
                'params': {'run': {'id': 'hook', 'eventName': 'preToolUse', 'status': 'completed'}},
            },
            {'method': 'item/started', 'params': {'item': tool}},
            {
                'method': 'item/completed',
                'params': {
                    'item': dict(
                        tool,
                        status='completed',
                        error=None,
                        result={k: v for k, v in self.result.items() if k != 'isError'},
                    )
                },
            },
            {'method': 'turn/completed', 'params': {'turn': {'status': 'completed', 'error': None}}},
        ]

    def write(self):
        (self.bridge / 'bridge.ndjson').write_bytes(b''.join(canonical(v) + b'\n' for v in self.ledger))
        (self.agent / 'codex-rpc.ndjson').write_bytes(
            b''.join(
                canonical(
                    dict(sequence=i + 1, direction='in', frame_base64=base64.b64encode(canonical(v) + b'\n').decode())
                )
                + b'\n'
                for i, v in enumerate(self.events)
            )
        )
        (self.agent / 'normalized.ndjson').write_text(json.dumps({'schema': 'codex-event-v1', 'raw_refs': [1]}) + '\n')

    def test_exact_bijection(self):
        self.write()
        self.assertEqual(reconcile(self.agent, self.bridge, catalog('judge_visual', 'web'))['bridge_calls'], 1)

    def test_missing_call(self):
        self.events.pop(3)
        self.write()
        with self.assertRaises(ValueError):
            reconcile(self.agent, self.bridge, catalog('judge_visual', 'web'))

    def test_bridge_error_is_projected_to_item_status(self):
        self.ledger[1]['result']['isError'] = True
        self.events[3]['params']['item']['status'] = 'failed'
        self.write()
        self.assertEqual(reconcile(self.agent, self.bridge, catalog('judge_visual', 'web'))['bridge_calls'], 1)
        self.events[3]['params']['item']['status'] = 'completed'
        self.write()
        with self.assertRaises(ValueError):
            reconcile(self.agent, self.bridge, catalog('judge_visual', 'web'))

    def test_caught_operation_failure_still_prevents_credit(self):
        self.ledger[1]['operation_failed'] = True
        self.write()
        with self.assertRaises(ValueError):
            reconcile(self.agent, self.bridge, catalog('judge_visual', 'web'))

    def test_native_recovery_requires_exact_marker_and_platform(self):
        from gui_agent_bench.authoring_recovery import recovery_result, VERSION

        marker = {'version': VERSION, 'sequence': 1, 'operation': 'step', 'status': 'reset'}
        result = recovery_result(marker)
        result['_meta'] = {META: 'session:1'}
        for row in self.ledger:
            row.update(tool='gui_step', arguments={'action': 'press', 'key': 'Escape'})
        self.ledger[1].update(result=result, operation_failed=True, recovery=marker, denied=False)
        for event in (self.events[2], self.events[3]):
            event['params']['item'].update(tool='gui_step', arguments={'action': 'press', 'key': 'Escape'})
        self.events[3]['params']['item'].update(
            status='failed', error=None, result={k: v for k, v in result.items() if k != 'isError'}
        )
        self.write()
        tools = catalog('test_visual', 'mobile')
        self.assertEqual(reconcile(self.agent, self.bridge, tools, 'mobile')['authoring_recoveries'], [marker])
        with self.assertRaises(ValueError):
            reconcile(self.agent, self.bridge, tools, 'web')
        del self.ledger[1]['recovery']
        self.write()
        with self.assertRaises(ValueError):
            reconcile(self.agent, self.bridge, tools, 'mobile')

    def test_forged_result(self):
        self.events[3]['params']['item']['result'] = dict(self.result, content=[{'type': 'text', 'text': 'forged'}])
        self.write()
        with self.assertRaises(ValueError):
            reconcile(self.agent, self.bridge, catalog('judge_visual', 'web'))

    def test_missing_hook(self):
        self.events.pop(1)
        self.write()
        with self.assertRaises(ValueError):
            reconcile(self.agent, self.bridge, catalog('judge_visual', 'web'))

    def test_unsettled_ledger(self):
        self.ledger.pop()
        self.write()
        with self.assertRaises(ValueError):
            reconcile(self.agent, self.bridge, catalog('judge_visual', 'web'))

    def test_normalized_forgery(self):
        self.write()
        (self.agent / 'normalized.ndjson').write_text('{"schema":"codex-event-v1","raw_refs":[999]}\n')
        with self.assertRaises(ValueError):
            reconcile(self.agent, self.bridge, catalog('judge_visual', 'web'))

    def test_viewer_preserves_runner_contract(self):
        event = self.events[3]
        event['params'].update(threadId='thread', turnId='turn')
        decoded = envelope(
            {'sequence': 1, 'direction': 'in', 'frame_base64': base64.b64encode(canonical(event)).decode()}
        )
        self.assertEqual(identity(decoded), ('thread', 'turn', 'item'))
        view = presentation(decoded)
        self.assertEqual(view['kind'], 'codex_tool')
        self.assertEqual(view['output'], self.result['content'])
        self.assertEqual(view['call_id'], 'session:1')


class PlatformAuditTests(unittest.TestCase):
    def test_codex_judges_enforce_platform_boundary_before_grading(self):
        from unittest.mock import patch
        from gui_agent_bench.audit import audit_run

        for platform, target in [
            ('mobile', 'gui_agent_bench.mobile_audit.audit_mobile'),
            ('tv', 'gui_agent_bench.tv_session.audit_app'),
        ]:
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                trial = folder / 'trials' / '0123456789abcdef'
                trial.mkdir(parents=True)
                (folder / 'plan.json').write_text(
                    json.dumps(
                        {
                            'arm': 'judge_visual',
                            'platform': platform,
                            'task': platform + '/fixture',
                            'runner': 'codex',
                            'planned_trials': 1,
                            'trials': [{'id': trial.name}],
                        }
                    )
                )
                (trial / 'workspace-manifest.json').write_text(
                    json.dumps({'arm': 'judge_visual', 'platform': platform})
                )
                with (
                    patch('gui_agent_bench.codex_audit.audit_codex_authoring', return_value=({}, set(), set())),
                    patch(target, side_effect=ValueError('platform boundary denied')) as audit,
                ):
                    with self.assertRaisesRegex(ValueError, 'platform boundary denied'):
                        audit_run(folder)
                    audit.assert_called_once_with(trial)
