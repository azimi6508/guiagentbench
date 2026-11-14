import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from gui_agent_bench.codex_bridge import Bridge, catalog
from gui_agent_bench.io import digest


@unittest.skipUnless(importlib.util.find_spec('jsonschema'), 'Codex extra required')
class BridgeTests(unittest.TestCase):
    def test_native_extended_catalog_matches_actual_broker_without_visual_ui_leak(self):
        from gui_agent_bench.broker import TOOLS, platform_tools
        from gui_agent_bench.oracle_broker import tools_for

        for arm in ('judge_test', 'oracle_visual', 'oracle_ui', 'test_visual', 'test_ui'):
            tools = catalog(arm, 'mobile', 'native_extended')
            gui = [{**t, 'name': t['name'][4:]} for t in tools if t['name'].startswith('gui_')]
            self.assertEqual(
                gui, platform_tools(TOOLS if arm == 'judge_test' else tools_for(arm), 'mobile', 'native_extended')
            )
            self.assertEqual(any(t['name'] == 'dump_ui' for t in gui), not arm.endswith('_visual'))
            step = next(t for t in gui if t['name'] == 'step')
            self.assertIn('open_app', step['inputSchema']['properties']['action']['enum'])
            self.assertIn('long_press', step['inputSchema']['properties']['action']['enum'])
        generic = next(t for t in catalog('test_ui', 'mobile') if t['name'] == 'gui_step')
        self.assertNotIn('open_app', generic['inputSchema']['properties']['action']['enum'])
        for platform, profile in [('web', 'native_extended'), ('tv', 'native_extended'), ('mobile', 'unknown')]:
            with self.assertRaises(ValueError):
                catalog('test_visual', platform, profile)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.output = self.root / 'output'
        self.output.mkdir()
        self.data = ('a' * 17000 + '🧑🏽‍💻e\u0301' + 'x' * 9000).encode()
        (self.workspace / 'instruction.md').write_bytes(self.data)
        self.manifest = {'files': {'instruction.md': digest(self.data)}}
        self.bridge = Bridge(
            self.workspace, self.output, self.root / 'audit', self.manifest, 'judge_visual', 'web', (960, 640)
        )

    def call(self, name, args):
        return self.bridge.call(name, args, 7)

    def test_zero_call_session_has_explicit_empty_ledger(self):
        from gui_agent_bench.codex_audit import reconcile

        ledger = self.root / 'audit/bridge.ndjson'
        self.assertEqual(ledger.read_bytes(), b'')
        agent = self.root / 'agent'
        agent.mkdir()
        frame = {'method': 'turn/completed', 'params': {'turn': {'status': 'completed', 'error': None}}}
        raw = {'sequence': 1, 'direction': 'in', 'frame_base64': base64.b64encode(json.dumps(frame).encode()).decode()}
        (agent / 'codex-rpc.ndjson').write_text(json.dumps(raw) + '\n')
        (agent / 'normalized.ndjson').write_text(json.dumps({'schema': 'codex-event-v1', 'raw_refs': [1]}) + '\n')
        self.assertEqual(reconcile(agent, self.root / 'audit', catalog('judge_visual', 'web'))['bridge_calls'], 0)
        ledger.unlink()
        with self.assertRaises(FileNotFoundError):
            reconcile(agent, self.root / 'audit', catalog('judge_visual', 'web'))

    def test_bridge_restart_cannot_overwrite_existing_evidence(self):
        ledger = self.root / 'audit/bridge.ndjson'
        ledger.write_bytes(b'preserved\n')
        with self.assertRaises(FileExistsError):
            Bridge(self.workspace, self.output, self.root / 'audit', self.manifest, 'judge_visual', 'web', (960, 640))
        self.assertEqual(ledger.read_bytes(), b'preserved\n')

    def text(self, result):
        self.assertFalse(result['isError'], result)
        return json.loads(result['content'][0]['text'])

    def test_catalog_matrix(self):
        for platform in ['web', 'mobile', 'tv']:
            for arm in ['judge_visual', 'judge_test', 'oracle_visual', 'oracle_ui', 'test_visual', 'test_ui']:
                if platform == 'tv' and arm.endswith('_ui'):
                    with self.assertRaises(ValueError):
                        catalog(arm, platform)
                    continue
                names = {t['name'] for t in catalog(arm, platform)}
                self.assertEqual('gui_dump_ui' in names, not arm.endswith('_visual') and platform != 'tv')
                self.assertEqual('gui_open_url' in names, arm != 'judge_visual' and platform != 'tv')
                if arm == 'judge_visual':
                    self.assertEqual(len(names), 4)

    def test_pagination_exact_utf8(self):
        for size in [4, 7, 8192]:
            offset = 0
            recovered = b''
            while True:
                page = self.text(
                    self.bridge.operation(
                        'bench_read_file', dict(path='/workspace/instruction.md', offset=offset, max_bytes=size)
                    )
                )
                recovered += page['text'].encode()
                if page['eof']:
                    break
                offset = page['next_offset']
                # Small-page tests exercise pure operation to avoid exhausting
                # the deliberate per-trial admission limit.
            self.assertEqual(recovered, self.data)

    def test_multibyte_offset_and_bool(self):
        for extra in [
            dict(offset=17001),
            dict(offset=True),
            dict(max_bytes=False),
            dict(offset=len(self.data) + 1),
            dict(max_bytes=3),
        ]:
            self.assertTrue(self.call('bench_read_file', dict(path='/workspace/instruction.md', **extra))['isError'])

    def test_empty_eof_page(self):
        value = self.text(self.call('bench_read_file', dict(path='/workspace/instruction.md', offset=len(self.data))))
        self.assertEqual(value['text'], '')
        self.assertTrue(value['eof'])
        self.assertIsNone(value['next_offset'])

    def test_oversized_read_explains_the_public_pagination_limit(self):
        result = self.call('bench_read_file', dict(path='/workspace/instruction.md', max_bytes=20000))
        self.assertTrue(result['isError'])
        message = json.loads(result['content'][0]['text'])
        self.assertEqual(message['cause'], 'invalid_arguments')
        self.assertIn('8192', message['message'])
        self.assertIn('next_offset', message['message'])
        self.assertFalse(self.bridge.fatal)
        page = self.text(self.call('bench_read_file', dict(path='/workspace/instruction.md')))
        self.assertEqual(page['end_offset'], 8192)

    def test_all_forbidden_paths(self):
        paths = [
            '/private/labels.json',
            '/setup/source.py',
            '/artifact/oracle.py',
            '/config/config.toml',
            '/auth-input/auth.json',
            '/run/codex/auth.json',
            '/run/codex/sessions',
            '/audit/bridge.ndjson',
            '/proc/self/environ',
            '/proc/self/fd/0',
            '/proc/1/root/run/codex/auth.json',
            '/dev/fd/0',
            '/etc/passwd',
            '/workspace/output/../escape.txt',
            '/workspace//instruction.md',
            '/workspace/./instruction.md',
            'file:///workspace/instruction.md',
            'C:\\Users\\x\\auth.json',
            '/workspace/instruction.md/',
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(self.call('bench_read_file', {'path': path})['isError'])

    def test_manifest_hash_tampering(self):
        (self.workspace / 'instruction.md').write_text('changed')
        self.assertTrue(self.call('bench_read_file', {'path': '/workspace/instruction.md'})['isError'])
        self.assertTrue(self.bridge.fatal)

    def test_unknown_tool_no_dispatch(self):
        self.assertTrue(self.call('bench_shell', {'command': 'touch escaped'})['isError'])
        self.assertFalse((self.output / 'escaped').exists())

    def test_atomic_compare_and_replace(self):
        args = dict(path='/workspace/output/sub/scratch.txt', content='old')
        first = self.text(self.call('bench_write_file', args))
        denied = self.call('bench_write_file', dict(args, content='new', expected_sha256='0' * 64))
        self.assertTrue(denied['isError'])
        self.assertEqual((self.output / 'sub/scratch.txt').read_text(), 'old')
        result = self.text(self.call('bench_write_file', dict(args, content='new', expected_sha256=first['sha256'])))
        self.assertEqual(result['previous_sha256'], first['sha256'])
        self.assertEqual((self.output / 'sub/scratch.txt').read_text(), 'new')
        self.assertFalse(list(self.output.rglob('.atomic-*')))

    def test_control_character_write_cap(self):
        self.text(self.call('bench_write_file', dict(path='/workspace/output/scratch', content='\x01' * 65536)))
        self.assertTrue(
            self.call('bench_write_file', dict(path='/workspace/output/scratch', content='\x01' * 65537))['isError']
        )
        self.assertEqual((self.output / 'scratch').stat().st_size, 65536)

    def test_judgment_limit(self):
        self.assertTrue(
            self.call('bench_write_file', dict(path='/workspace/output/judgment.json', content='x' * 16385))['isError']
        )

    def test_symlink_and_hardlink_denied(self):
        import os

        target = self.root / 'hidden'
        target.write_text('CANARY')
        (self.output / 'link').symlink_to(target)
        self.assertTrue(self.call('bench_read_file', dict(path='/workspace/output/link'))['isError'])
        (self.output / 'link').unlink()
        os.link(target, self.output / 'hard')
        self.assertTrue(
            self.call('bench_write_file', dict(path='/workspace/output/hard', content='changed'))['isError']
        )
        self.assertEqual(target.read_text(), 'CANARY')

    def test_parent_symlink_denied(self):
        (self.output / 'sub').symlink_to(self.root, target_is_directory=True)
        self.assertTrue(
            self.call('bench_write_file', dict(path='/workspace/output/sub/escaped', content='x'))['isError']
        )
        self.assertFalse((self.root / 'escaped').exists())

    def test_path_quotas(self):
        for path in ['a/b/c/d/e', 'x' * 65]:
            self.assertTrue(
                self.call('bench_write_file', dict(path='/workspace/output/' + path, content='x'))['isError']
            )

    def test_count_quota_and_replacement(self):
        for i in range(128):
            (self.output / str(i)).write_text('x')
        self.text(self.call('bench_write_file', dict(path='/workspace/output/0', content='replace')))
        self.assertTrue(self.call('bench_write_file', dict(path='/workspace/output/extra', content='x'))['isError'])

    def test_ledger_complete_content_and_ids(self):
        result = self.call(
            'bench_write_file', dict(path='/workspace/output/test.py', content='def test(page):\n    pass\n')
        )
        records = [json.loads(l) for l in (self.root / 'audit/bridge.ndjson').read_text().splitlines()]
        self.assertEqual([r['phase'] for r in records], ['started', 'completed'])
        self.assertEqual(records[0]['arguments']['content'], 'def test(page):\n    pass\n')
        self.assertEqual(result['_meta'], records[1]['result']['_meta'])

    def test_call_limit_counts_denials(self):
        self.bridge.count = 480
        self.assertTrue(self.call('bench_list_files', {})['isError'])
        self.assertTrue(self.bridge.fatal)
