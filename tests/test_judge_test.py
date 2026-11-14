"""Tests for executable-vs-readable evidence and broker capability boundaries."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from gui_agent_bench.broker import validate_call
from gui_agent_bench.materialize import materialize, validate_workspace
from gui_agent_bench.runners.opencode import configuration
from gui_agent_bench.audit import audit_agent


class JudgeTestBoundaries(unittest.TestCase):
    def test_source_is_exact_but_no_visual_or_private_evidence_is_copied(self):
        task = ROOT / 'tasks/web/webarena-399-profile-bio'
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / 'workspace'
            manifest = materialize(ROOT, task, Path(temp) / 'absent', workspace, 'judge_test')
            self.assertEqual(set(manifest['files']), {'instruction.md', 'test_source.py'})
            self.assertEqual(
                (workspace / 'test_source.py').read_bytes(), (task / 'private/test_source.py').read_bytes()
            )
            validate_workspace(workspace, manifest)

    def test_broker_rejects_code_batches_paths_and_network_escapes(self):
        for tool, args in [
            ('execute', {'code': 'print(1)'}),
            ('step', {'action': 'evaluate', 'code': '1+1'}),
            ('step', {'action': 'click', 'role': 'button', 'name': 'Add item', 'script': '1+1'}),
            ('step', [{'action': 'reload'}]),
            ('observe', {'path': '/private/labels.json'}),
            ('dump_ui', {'selector': 'script'}),
            ('reset', {'test': '/workspace/test_source.py'}),
            ('open_url', {'url': 'http://app:8000/private/labels.json'}),
            ('open_url', {'url': 'http://app:8000@provider:8080/'}),
            ('open_url', {'url': 'file:///private/labels.json'}),
            ('step', {'action': 'press', 'role': 'button', 'name': 'Add item', 'key': 'F12'}),
        ]:
            with self.subTest(tool=tool, args=args), self.assertRaises(ValueError):
                validate_call(tool, args)

    def test_broker_accepts_individual_user_actions_only(self):
        for tool, args in [
            ('observe', {}),
            ('dump_ui', {}),
            ('reset', {}),
            ('open_url', {'url': 'http://app:8000/'}),
            ('step', {'action': 'reload'}),
            ('step', {'action': 'click', 'role': 'button', 'name': 'Add item'}),
            ('step', {'action': 'hover', 'role': 'button', 'name': 'Travel'}),
            ('step', {'action': 'fill', 'role': 'textbox', 'name': 'Message', 'text': 'hello'}),
            ('step', {'action': 'press', 'role': 'textbox', 'name': 'Message', 'key': 'Enter'}),
        ]:
            validate_call(tool, args)

    def test_only_live_judge_registers_the_broker(self):
        with tempfile.TemporaryDirectory() as temp:
            for arm in ['judge_visual', 'judge_test']:
                config = configuration(ROOT, Path(temp) / 'config.json', 'relay', 'fixture', arm)
                self.assertEqual(bool(config['mcp']), arm == 'judge_test')
                self.assertEqual(config['permission']['bash'], 'deny')
                self.assertEqual(config['permission']['*'], 'deny')

    def test_audit_requires_exact_live_transport_headers(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp).resolve()
            workspace = folder / 'workspace'
            manifest = materialize(
                ROOT, ROOT / 'tasks/web/webarena-399-profile-bio', folder / 'absent', workspace, 'judge_test'
            )
            config = configuration(ROOT, folder / 'config.json', 'relay', 'scripted', 'judge_test')
            details = {
                'HostConfig': {
                    'ReadonlyRootfs': True,
                    'Privileged': False,
                    'CapDrop': ['ALL'],
                    'SecurityOpt': ['no-new-privileges'],
                },
                'Config': {'User': 'node', 'Env': []},
                'Image': 'fixture',
                'NetworkSettings': {'Networks': {'isolated': {}}},
                'Mounts': [
                    {'Type': 'bind', 'Destination': destination, 'Source': str(source), 'RW': writable}
                    for destination, source, writable in [
                        ('/workspace', workspace, False),
                        ('/workspace/output', folder / 'output', True),
                        ('/config', folder / 'config', False),
                    ]
                ],
            }
            self.assertEqual(audit_agent(details, workspace, manifest, config, {'Internal': True})['status'], 'pass')
            for headers in [
                None,
                {},
                {'Connection': 'keep-alive'},
                {'Connection': 'close', 'Authorization': 'unexpected'},
            ]:
                changed = json.loads(json.dumps(config))
                if headers is None:
                    changed['mcp']['gui'].pop('headers')
                else:
                    changed['mcp']['gui']['headers'] = headers
                with self.subTest(headers=headers), self.assertRaises(ValueError):
                    audit_agent(details, workspace, manifest, changed, {'Internal': True})


if __name__ == '__main__':
    unittest.main()


class TVJudgmentContractTests(unittest.TestCase):
    pass
