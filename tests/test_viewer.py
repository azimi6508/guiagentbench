"""Viewer evidence semantics, live updates and loopback serving boundaries."""

import base64
import hashlib
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest
import sys
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from gui_agent_bench.viewer.evidence import EvidenceIndex
from gui_agent_bench.viewer.server import ViewerServer
from gui_agent_bench.viewer.app import ViewerServer as ReviewServer

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGZkAAAAASUVORK5CYII=')


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'run-one'
        self.run.mkdir()
        self.put(
            'plan.json',
            {
                'task': 'web/example',
                'arm': 'test_visual',
                'model': 'fixture/scripted',
                'fixture': True,
                'planned_trials': 2,
                'planned_executions': 2,
                'trials': [{'id': 'a', 'variant': 'correct'}, {'id': 'missing', 'variant': 'faulty'}],
            },
        )
        self.put('summary.json', {'status': 'running', 'completed_trials': 0, 'paired_score': 0})
        self.index = EvidenceIndex(self.root)
        self.rid = self.index.listing()['runs'][0]['id']
        self.stream = 'trials/a/logs/agent/trajectory.ndjson'

    def put(self, relative, value):
        path = self.run / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def events(self, values, tail=''):
        path = self.run / self.stream
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(v) + '\n' for v in values) + tail, encoding='utf-8')
        return path

    def test_planned_missing_cell_is_preserved_with_original_zero(self):
        detail = self.index.detail(self.rid)
        self.assertEqual(detail['plan']['planned_trials'], 2)
        self.assertEqual(len(detail['trials']), 2)
        self.assertTrue(detail['trials'][1]['missing'])
        self.assertEqual(detail['summary']['paired_score'], 0)
        self.assertTrue(any('metrics.json' in w['file'] for w in detail['warnings']))

    def test_provisional_scores_and_single_state_runs_are_not_final_pairs(self):
        row = self.index.listing()['runs'][0]
        self.assertEqual(row['score'], 0)
        self.assertEqual(row['outcome'], 'unresolved')
        self.put(
            'plan.json',
            {
                'task': 'web/example',
                'arm': 'judge_visual',
                'planned_trials': 1,
                'trials': [{'id': 'a', 'variant': 'correct'}],
            },
        )
        self.put('summary.json', {'status': 'complete', 'paired_score': None, 'planned_pairs': 0, 'accuracy': 1})
        row = self.index.listing()['runs'][0]
        self.assertFalse(row['paired'])
        self.assertEqual(row['outcome'], 'unpaired')

    def test_live_updates_append_finish_and_new_run(self):
        path = self.events([{'type': 'text', 'part': {'text': 'start'}}])
        self.assertEqual(self.index.events(self.rid, self.stream)['total'], 1)
        with path.open('a', encoding='utf-8') as out:
            out.write(json.dumps({'type': 'text', 'part': {'text': 'finish'}}) + '\n')
        self.assertEqual(self.index.events(self.rid, self.stream)['events'][1]['output'], 'finish')
        self.put('summary.json', {'status': 'complete', 'completed_trials': 1, 'paired_score': 0})
        self.assertEqual(self.index.detail(self.rid)['summary']['status'], 'complete')
        new = self.root / 'new-run'
        new.mkdir()
        (new / 'plan.json').write_text((self.run / 'plan.json').read_text())
        self.index.refresh(force=True)
        self.assertEqual(len(self.index.listing()['runs']), 2)

    def test_partial_tail_visible_and_repaired_without_drop(self):
        path = self.events([{'type': 'text'}], '{"type":')
        before = self.index.events(self.rid, self.stream)
        self.assertEqual(before['total'], 2)
        self.assertEqual(before['events'][1]['error'], 'Incomplete final record')
        with path.open('a') as out:
            out.write('"step_finish"}\n')
        after = self.index.events(self.rid, self.stream)
        self.assertEqual(after['total'], 2)
        self.assertIsNone(after['events'][1]['error'])

    def test_recovery_times_not_original_times_and_order_not_sorted(self):
        self.events(
            [
                {
                    'type': 'tool_use',
                    'timestamp': 5000,
                    'source': 'opencode-session-api',
                    'part': {'id': 'p1', 'state': {'time': {'start': 100}}},
                },
                {'type': 'text', 'timestamp': 5001, 'source': 'opencode-session-api', 'part': {'text': 'recovered'}},
                {'type': 'text', 'timestamp': 50},
            ]
        )
        events = self.index.events(self.rid, self.stream)['events']
        self.assertEqual([e['time'] for e in events], [100, None, 50])
        self.assertEqual(events[1]['recovery_time'], 5001)
        self.assertEqual([e['line'] for e in events], [1, 2, 3])

    def test_same_part_revisions_coalesced_without_losing_source_lines(self):
        self.events(
            [
                {
                    'type': 'tool_use',
                    'sessionID': 's',
                    'part': {'id': 'p', 'messageID': 'm', 'state': {'status': 'running'}},
                },
                {
                    'type': 'tool_use',
                    'sessionID': 's',
                    'part': {'id': 'p', 'messageID': 'm', 'state': {'status': 'completed'}},
                },
            ]
        )
        result = self.index.events(self.rid, self.stream)
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['events'][0]['revisions'], [1, 2])
        self.assertEqual(result['events'][0]['status'], 'completed')

    def test_pagination_reaches_all_events(self):
        self.events([{'type': 'text', 'part': {'text': str(i)}} for i in range(143)])
        seen = []
        offset = 0
        while offset is not None:
            page = self.index.events(self.rid, self.stream, offset, 60)
            seen.extend(e['output'] for e in page['events'])
            offset = page['next']
        self.assertEqual(seen, [str(i) for i in range(143)])

    def test_embedded_image_linkage_and_no_remote_fetch(self):
        url = 'data:image/png;base64,' + base64.b64encode(PNG).decode()
        self.events(
            [
                {
                    'type': 'tool_use',
                    'part': {'state': {'attachments': [{'url': url}, {'url': 'https://evil.example/x.png'}]}},
                }
            ]
        )
        event = self.index.events(self.rid, self.stream)['events'][0]
        self.assertEqual(len(event['images']), 1)
        digest = hashlib.sha256(PNG).hexdigest()
        self.assertEqual(event['images'][0]['sha256'], digest)
        self.assertNotIn(base64.b64encode(PNG).decode(), json.dumps(event))
        self.assertEqual(self.index.embedded_image(self.rid, self.stream, 1, digest), ('image/png', PNG))
        with self.assertRaises(FileNotFoundError):
            self.index.embedded_image(self.rid, self.stream, 1, 'wrong')

    def test_nested_runs_and_verification_not_double_counted(self):
        self.put(
            'trials/a/verification/plan.json',
            {'arm': 'test_visual', 'executions': [{'id': 'one', 'variant': 'correct'}]},
        )
        nested = self.root / 'campaign' / 'runs' / 'child'
        nested.mkdir(parents=True)
        (nested / 'plan.json').write_text((self.run / 'plan.json').read_text())
        self.index.refresh(force=True)
        self.assertEqual(len(self.index.listing()['runs']), 2)
        self.assertEqual(len(self.index.detail(self.rid)['trials'][0]['executions']), 1)

    def test_single_run_root(self):
        idx = EvidenceIndex(self.run)
        self.assertEqual(len(idx.listing()['runs']), 1)

    def test_external_execution_summary(self):
        self.put(
            'plan.json',
            {
                'arm': 'oracle_ui',
                'planned_executions': 2,
                'executions': [{'id': 'one', 'variant': 'correct'}, {'id': 'two', 'variant': 'faulty'}],
            },
        )
        self.put('logs/verifier/metrics.json', {'status': 'graded', 'reward': 1, 'completed_executions': 2})
        self.index.refresh(force=True)
        detail = self.index.detail(self.rid)
        self.assertEqual(detail['summary']['reward'], 1)
        self.assertEqual(len(detail['trials'][0]['executions']), 2)
        self.assertEqual(self.index.listing()['runs'][0]['score'], 1)

    def test_unknown_cost_is_not_free(self):
        path = self.run / 'trials/a/logs/provider.ndjson'
        path.parent.mkdir(parents=True)
        path.write_text(
            '\n'.join(
                json.dumps(x)
                for x in [{'usage': {'cost': 0.25}}, {'usage': {'cost': None}}, {'usage': {'tokens': 100}}]
            )
        )
        cost = self.index.detail(self.rid)['cost']
        self.assertEqual(cost['known_usd'], 0.25)
        self.assertEqual(cost['unknown_records'], 2)
        self.assertEqual(cost['records'], 3)

    def test_reference_provenance_and_sealed_hashes_are_verified(self):
        url = 'data:image/png;base64,' + base64.b64encode(PNG).decode()
        self.events([{'type': 'tool_use', 'part': {'state': {'attachments': [{'url': url}]}}}])
        sha = hashlib.sha256(PNG).hexdigest()
        self.put(
            'trials/a/sealed/references/manifest.json',
            {'references': {'screen': {'file': 'screen.png', 'sha256': sha}}},
        )
        (self.run / 'trials/a/sealed/references/screen.png').write_bytes(PNG)
        program = self.run / 'trials/a/sealed/test.py'
        program.write_bytes(b'def test(page): pass\n')
        self.put('trials/a/submission.json', {'sha256': hashlib.sha256(program.read_bytes()).hexdigest()})
        trial = self.index.detail(self.rid)['trials'][0]
        self.assertTrue(trial['sealed_hash_matches'])
        self.assertTrue(trial['references'][0]['hash_matches'])
        self.assertEqual(trial['references'][0]['observation']['line'], 1)
        program.write_bytes(b'changed\n')
        self.assertFalse(self.index.detail(self.rid)['trials'][0]['sealed_hash_matches'])

    def test_resources_count_part_revisions_once_and_unknown_stays_unknown(self):
        event = {'type': 'step_finish', 'sessionID': 's', 'part': {'id': 'p', 'tokens': {'input': 100, 'output': 50}}}
        self.events([event, event])
        resources = self.index.detail(self.rid)['trials'][0]['resources']
        self.assertEqual(resources['recorded_steps'], 1)
        self.assertEqual(resources['input_tokens'], 100)
        self.assertEqual(resources['output_tokens'], 50)
        self.assertIsNone(resources['reasoning_tokens'])

    def test_host_entrypoint_delegates_existing_commands_unchanged(self):
        from gui_agent_bench import entrypoint
        from unittest.mock import patch

        argv = ['--root', str(self.root), 'run', '--model', 'fixture/scripted']
        with patch.object(entrypoint.cli, 'main', return_value=7) as main:
            self.assertEqual(entrypoint.main(argv), 7)
            main.assert_called_once_with(argv)
        (self.root / 'runs').mkdir(exist_ok=True)
        with patch('gui_agent_bench.viewer.app.serve') as serve:
            self.assertEqual(entrypoint.main(['--root', str(self.root), 'view', '--no-open', '--port', '8089']), 0)
            serve.assert_called_once_with(self.root / 'runs', 8089, open_browser=False)

    def test_allowlist_excludes_private_gold_active_files_and_traversal(self):
        for path in [
            'gold/result.json',
            'trials/a/capture/screenshots/0001.png',
            'private/labels.json',
            'trials/a/agent-container.json',
            'workspace/site.html',
            '../plan.json',
            'plan.json:stream',
            'trials/a/../../plan.json',
            'C:/secret.txt',
            'trials\\a\\summary.json',
        ]:
            with self.subTest(path=path), self.assertRaises((ValueError, FileNotFoundError)):
                self.index.artifact(self.rid, path)
        self.put('trials/a/gold/gold-result.json', {'secret': True})
        self.assertFalse(any('gold' in a['path'] for a in self.index.detail(self.rid)['artifacts']))

    def test_real_materialized_input_layout_and_provenance(self):
        filename = 'evidence/screenshots/0001.png'
        path = self.run / ('trials/a/workspace/' + filename)
        path.parent.mkdir(parents=True)
        path.write_bytes(PNG)
        sha = hashlib.sha256(PNG).hexdigest()
        self.put('trials/a/workspace/evidence/manifest.json', {'frames': []})
        self.put(
            'trials/a/workspace-manifest.json',
            {
                'files': {
                    filename: sha,
                    'instruction.md': 'missing',
                    'test_source.py': 'wrong',
                    '../../private/labels.json': 'not-a-permission',
                }
            },
        )
        self.put('trials/a/workspace/test_source.py', 'saved source')
        self.events(
            [
                {
                    'type': 'tool_use',
                    'part': {
                        'tool': 'read',
                        'state': {
                            'status': 'completed',
                            'input': {'filePath': '/workspace/' + filename},
                            'attachments': [{'url': 'data:image/png;base64,' + base64.b64encode(PNG).decode()}],
                        },
                    },
                }
            ]
        )
        trial = self.index.detail(self.rid)['trials'][0]
        inputs = {item['name']: item for item in trial['inputs']}
        self.assertTrue(inputs[filename]['hash_matches'])
        self.assertEqual(inputs[filename]['reads'], [{'file': self.stream, 'line': 1}])
        self.assertEqual(inputs[filename]['observation'], {'file': self.stream, 'line': 1})
        self.assertFalse(inputs['instruction.md']['present'])
        self.assertIsNone(inputs['instruction.md']['hash_matches'])
        self.assertFalse(inputs['test_source.py']['hash_matches'])
        self.assertEqual(inputs['test_source.py']['reads'], [])
        self.assertNotIn('../../private/labels.json', inputs)
        self.assertEqual(trial['workspace_manifest'], 'trials/a/workspace-manifest.json')
        self.assertEqual(self.index.artifact(self.rid, 'trials/a/workspace/' + filename).read_bytes(), PNG)

    def test_failed_read_is_not_claimed_as_access_and_draft_is_not_sealed(self):
        self.put('trials/a/workspace/instruction.md', 'task')
        self.put('trials/a/output/test.py', 'incomplete draft')
        self.put('trials/a/output/other.html', 'active content')
        self.put('trials/a/mobile-driver.log', 'driver startup failed')
        self.events(
            [
                {
                    'part': {
                        'tool': 'read',
                        'state': {'status': 'error', 'input': {'filePath': '/workspace/instruction.md'}},
                    }
                }
            ]
        )
        trial = self.index.detail(self.rid)['trials'][0]
        self.assertEqual(trial['inputs'][0]['reads'], [])
        self.assertIsNone(trial['inputs'][0]['hash_matches'])
        self.assertIsNone(trial['sealed_file'])
        self.assertEqual(trial['draft_files'], ['trials/a/output/test.py'])
        self.assertTrue(self.index.artifact(self.rid, 'trials/a/mobile-driver.log').is_file())
        with self.assertRaises(ValueError):
            self.index.artifact(self.rid, 'trials/a/output/other.html')

    def test_input_read_revisions_count_one_call_and_broker_failure_is_visible(self):
        self.put('trials/a/workspace/instruction.md', 'task')
        event = {
            'sessionID': 's',
            'part': {
                'id': 'p',
                'messageID': 'm',
                'tool': 'read',
                'state': {'status': 'completed', 'input': {'filePath': '/workspace/instruction.md'}},
            },
        }
        self.events([event, event, {'failure': {'cause': 'reset_failure', 'message': 'Reset failed'}}])
        trial = self.index.detail(self.rid)['trials'][0]
        self.assertEqual(trial['inputs'][0]['reads'], [{'file': self.stream, 'line': 2}])
        self.assertEqual(self.index.events(self.rid, self.stream)['events'][1]['error'], 'Reset failed')

    def test_symlink_rejected_in_index_and_after_registration(self):
        target = self.root / 'outside.json'
        target.write_text('secret')
        path = self.run / 'audit.json'
        try:
            path.symlink_to(target)
        except OSError as exc:
            self.skipTest(f'Symlinks unavailable: {exc}')
        self.assertNotIn('audit.json', [a['path'] for a in self.index.detail(self.rid)['artifacts']])
        with self.assertRaises(ValueError):
            self.index.artifact(self.rid, 'audit.json')

    def test_reads_do_not_modify_originals(self):
        self.events([{'type': 'text'}])
        before = {
            p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in self.root.rglob('*')
            if p.is_file()
        }
        self.index.listing()
        self.index.detail(self.rid)
        self.index.events(self.rid, self.stream)
        after = {
            p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in self.root.rglob('*')
            if p.is_file()
        }
        self.assertEqual(before, after)

    def test_http_read_only_host_origin_pagination_and_inert_text(self):
        for server_class in (ViewerServer, ReviewServer):
            with self.subTest(server=server_class.__module__):
                self.http_boundary(server_class)

    def http_boundary(self, server_class):
        self.events([{'part': {'text': '<script>alert(1)</script>'}}])
        self.put('sealed/judgment.json', {'reason': '<script>alert(1)</script>'})
        server = server_class(self.root, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def get(path, method='GET', headers=None):
            connection = HTTPConnection(*server.server_address)
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            data = response.read()
            result = (response.status, dict(response.getheaders()), data)
            connection.close()
            return result

        params = urlencode({'id': self.rid, 'path': 'sealed/judgment.json'})
        status, headers, data = get('/api/artifact?' + params)
        self.assertEqual(status, 200)
        self.assertTrue(headers['Content-Type'].startswith('text/plain'))
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertIn(b'<script>', data)
        self.assertEqual(get('/api/runs', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(get('/api/runs', headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(get('/api/runs', method='POST')[0], 405)
        self.assertEqual(get('/api/events?' + urlencode({'id': self.rid, 'path': self.stream, 'limit': 1001}))[0], 400)
        self.assertEqual(get('/api/artifact?' + urlencode({'id': self.rid, 'path': '../plan.json'}))[0], 400)
        self.assertEqual(get('/')[0], 200)
        self.assertEqual(get('/app.js')[0], 200)
        hierarchy = get('/api/hierarchy')
        self.assertEqual(hierarchy[0], 200)
        self.assertEqual(json.loads(hierarchy[2])['runs'][0]['tasks'][0]['id'], 'web/example')
        self.assertEqual(get('/api/hierarchy', method='POST')[0], 405)
        self.assertEqual(get('/style.css')[0], 200)


if __name__ == '__main__':
    unittest.main()
