"""Readable trajectories, verdicts and run overviews derived from recorded evidence."""

import base64
import hashlib
from http.client import HTTPConnection
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from gui_agent_bench.viewer.evidence import EvidenceIndex
from gui_agent_bench.viewer.review import Reviewer, execution_timeline, short_reason, verdict
from gui_agent_bench.viewer.app import ViewerServer, static_file
from gui_agent_bench.viewer.trajectory import describe, parse_failure, read_wrapper

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGZkAAAAASUVORK5CYII=')
PNG_SHA = hashlib.sha256(PNG).hexdigest()
PNG_B64 = base64.b64encode(PNG).decode()


def frame(direction, value, sequence, monotonic=None):
    record = {
        'direction': direction,
        'frame_base64': base64.b64encode(json.dumps(value).encode()).decode(),
        'sequence': sequence,
    }
    if monotonic is not None:
        record['monotonic_offset'] = monotonic
    return record


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, relative, value, raw=False):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if raw:
            path.write_bytes(value) if isinstance(value, bytes) else path.write_text(value, encoding='utf-8')
        else:
            path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def lines(self, relative, records):
        self.put(relative, ''.join(json.dumps(r) + '\n' for r in records), raw=True)

    def index(self):
        index = EvidenceIndex(self.root)
        return index, Reviewer(index), {r['path']: r['id'] for r in index.listing()['runs']}


class CodexTrajectoryTests(Fixture):
    def codex_run(self, complete=True, blob=True):
        self.put(
            'ev/plan.json',
            {
                'task': 'web/example',
                'arm': 'test_visual',
                'model': 'codex/m',
                'runner': 'codex',
                'planned_trials': 1,
                'trials': [{'id': 't1', 'variant': 'correct'}],
            },
        )
        self.put('ev/summary.json', {'status': 'complete', 'paired_score': 1, 'completed_trials': 1})
        thread, turn = 'th', 'tu'
        item = lambda kind, method, value, ms: {
            'method': method,
            'params': {
                'item': value,
                'threadId': thread,
                'turnId': turn,
                ('startedAtMs' if method == 'item/started' else 'completedAtMs'): ms,
            },
            'emittedAtMs': ms,
        }
        tool = {
            'type': 'mcpToolCall',
            'id': 'call_1',
            'server': 'bench',
            'tool': 'gui_step',
            'status': 'inProgress',
            'arguments': {'action': 'click', 'x': 5, 'y': 7},
            'result': None,
        }
        done = dict(
            tool,
            status='completed',
            durationMs=40,
            result={
                'content': [{'type': 'text', 'text': 'Action completed.'}],
                '_meta': {'gui_agent_bench.bridge_call_id': 'b:1'},
            },
        )
        denied = {
            'type': 'mcpToolCall',
            'id': 'call_2',
            'tool': 'bench_read_file',
            'status': 'completed',
            'arguments': {'path': '/x', 'max_bytes': 99999},
            'result': {
                'content': [
                    {
                        'type': 'text',
                        'text': '{"cause":"invalid_arguments","message":"Operation denied.","version":"failure-v1"}',
                    }
                ],
                'isError': True,
                '_meta': {'gui_agent_bench.bridge_call_id': 'b:2'},
            },
        }
        observe = {
            'type': 'mcpToolCall',
            'id': 'call_3',
            'tool': 'gui_observe',
            'status': 'completed',
            'arguments': {'reference': 'saved'},
            'result': {
                'content': [
                    {'type': 'image', 'data': PNG_B64, 'mimeType': 'image/png'},
                    {
                        'type': 'text',
                        'text': 'Screenshot coordinate metadata: {"width": 1, "height": 1, "coordinate_space": "original_screenshot"}\n',
                    },
                ],
                '_meta': {'gui_agent_bench.bridge_call_id': 'b:3'},
            },
        }
        frames = [
            frame('out', {'id': 1, 'method': 'turn/start', 'params': {}}, 1),
            frame(
                'in',
                {
                    'method': 'thread/started',
                    'params': {'thread': {'model': 'm', 'reasoningEffort': 'medium', 'cliVersion': '9'}},
                },
                2,
            ),
            frame('in', {'method': 'turn/started', 'params': {'turn': {'id': turn}}, 'emittedAtMs': 1000}, 3, 1.0),
            frame(
                'in',
                item(
                    'userMessage',
                    'item/completed',
                    {'type': 'userMessage', 'id': 'u', 'content': [{'type': 'text', 'text': 'Do it'}]},
                    1001,
                ),
                4,
            ),
            frame(
                'in',
                item(
                    'reasoning', 'item/completed', {'type': 'reasoning', 'id': 'r', 'summary': [], 'content': []}, 1002
                ),
                5,
            ),
            frame('in', item('tool', 'item/started', tool, 1010), 6),
            frame('in', item('tool', 'item/completed', done, 1050), 7),
            frame('in', item('tool', 'item/completed', denied, 1060), 8),
            frame('in', item('tool', 'item/completed', observe, 1070), 9),
            frame(
                'in',
                {
                    'method': 'hook/completed',
                    'params': {
                        'run': {
                            'id': 'pre-tool-use:0:/h:call_9',
                            'eventName': 'preToolUse',
                            'status': 'blocked',
                            'entries': [{'kind': 'feedback', 'text': 'Capability not permitted.'}],
                        }
                    },
                    'emittedAtMs': 1080,
                },
                10,
                1.08,
            ),
            frame('out', {'id': 2, 'method': 'turn/interrupt', 'params': {}}, 11, 1.09),
            frame(
                'in',
                {
                    'method': 'thread/tokenUsage/updated',
                    'params': {
                        'tokenUsage': {
                            'total': {'inputTokens': 10, 'outputTokens': 3, 'totalTokens': 13},
                            'last': {'inputTokens': 10},
                        }
                    },
                    'emittedAtMs': 1090,
                },
                12,
            ),
            frame(
                'in',
                item(
                    'message',
                    'item/completed',
                    {'type': 'agentMessage', 'id': 'm', 'text': 'Saved.', 'phase': 'final_answer'},
                    1095,
                ),
                13,
            ),
        ]
        if complete:
            frames.append(
                frame(
                    'in',
                    {
                        'method': 'turn/completed',
                        'params': {'turn': {'status': 'interrupted', 'durationMs': 95}},
                        'emittedAtMs': 1100,
                    },
                    14,
                )
            )
        frames.append({'direction': 'in', 'privacy_projection': True, 'status': 'received', 'sequence': 15})
        self.lines('ev/trials/t1/logs/agent/codex-rpc.ndjson', frames)
        self.lines(
            'ev/trials/t1/logs/bridge/bridge.ndjson',
            [
                {'phase': 'completed', 'bridge_call_id': 'b:1', 'tool': 'gui_step', 'denied': False, 'result': {}},
                {
                    'phase': 'completed',
                    'bridge_call_id': 'b:2',
                    'tool': 'bench_read_file',
                    'denied': True,
                    'result': {'isError': True},
                },
                {
                    'phase': 'completed',
                    'bridge_call_id': 'b:3',
                    'tool': 'gui_observe',
                    'denied': False,
                    'result': {'content': [{'type': 'image', 'blob': f'images/{PNG_SHA}.png', 'sha256': PNG_SHA}]},
                },
            ],
        )
        if blob:
            self.put(f'ev/trials/t1/logs/bridge/images/{PNG_SHA}.png', PNG, raw=True)

    def test_codex_frames_become_readable_steps(self):
        self.codex_run()
        index, reviewer, ids = self.index()
        traj = reviewer.trajectory(ids['ev'], 't1')
        kinds = [s['kind'] for s in traj['steps']]
        self.assertEqual(
            kinds, ['prompt', 'reasoning', 'tool', 'tool', 'tool', 'blocked', 'interrupt', 'message', 'end']
        )
        prompt, reasoning, click, read, observe, blocked, interrupt, message, end = traj['steps']
        self.assertEqual(prompt['text'], 'Do it')
        self.assertTrue(reasoning['hidden'])
        self.assertEqual(
            (click['title'], click['point'], click['status'], click['duration_ms']),
            ('Click at (5, 7)', [5, 7], 'ok', 40),
        )
        self.assertEqual(click['source']['lines'], [6, 7])
        self.assertEqual(read['status'], 'denied')
        self.assertEqual(read['failure']['cause'], 'invalid_arguments')
        self.assertEqual(read['result']['kind'], 'text', 'a denied read is not presented as an empty file page')
        self.assertEqual(observe['images'][0]['artifact'], f'trials/t1/logs/bridge/images/{PNG_SHA}.png')
        self.assertEqual(observe['result']['screen']['width'], 1)
        self.assertEqual(
            (blocked['status'], blocked['call_id'], blocked['detail']),
            ('blocked', 'call_9', 'Capability not permitted.'),
        )
        self.assertEqual(interrupt['started_ms'], 1090, 'outbound time is aligned from the monotonic offset')
        self.assertIn('monotonic', interrupt['time_basis'])
        self.assertEqual(message['phase'], 'final_answer')
        self.assertEqual(traj['end']['status'], 'interrupted')
        self.assertEqual(traj['stats']['tokens']['input'], 10)
        self.assertEqual(traj['stats']['final_message'], 'Saved.')
        self.assertEqual(
            (traj['stats']['tool_calls'], traj['stats']['failed_tools'], traj['stats']['blocked']), (3, 1, 1)
        )

    def test_missing_completion_and_embedded_image_fallback(self):
        self.codex_run(complete=False, blob=False)
        index, reviewer, ids = self.index()
        traj = reviewer.trajectory(ids['ev'], 't1')
        self.assertEqual(traj['end']['status'], 'interrupted')
        self.assertTrue(traj['warnings'])
        observe = next(s for s in traj['steps'] if s.get('tool') == 'gui_observe')
        embedded = observe['images'][0]['embedded']
        mime, data = index.embedded_image(ids['ev'], embedded['path'], embedded['line'], PNG_SHA)
        self.assertEqual((mime, data), ('image/png', PNG))

    def test_trajectory_cache_follows_appended_evidence(self):
        self.codex_run(complete=False)
        index, reviewer, ids = self.index()
        self.assertEqual(reviewer.trajectory(ids['ev'], 't1')['end']['status'], 'interrupted')
        path = self.root / 'ev/trials/t1/logs/agent/codex-rpc.ndjson'
        with path.open('a', encoding='utf-8') as out:
            out.write(
                json.dumps(
                    frame(
                        'in',
                        {'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}, 'emittedAtMs': 1200},
                        20,
                    )
                )
                + '\n'
            )
        self.assertEqual(reviewer.trajectory(ids['ev'], 't1')['end']['status'], 'completed')
        with self.assertRaises(ValueError):
            reviewer.trajectory(ids['ev'], '../t1')


class OpenCodeTrajectoryTests(Fixture):
    def test_parts_coalesce_tokens_sum_and_failures_classify(self):
        self.put(
            'oc/plan.json',
            {
                'task': 'web/example',
                'arm': 'judge_test',
                'model': 'provider/model',
                'planned_trials': 1,
                'trials': [{'id': 't1', 'variant': 'correct'}],
            },
        )
        part = lambda pid, msg, **kw: {'id': pid, 'messageID': msg, 'sessionID': 's', **kw}
        read_state = {
            'status': 'completed',
            'input': {'filePath': '/workspace/instruction.md', 'offset': 3, 'limit': 2},
            'output': '<path>/workspace/instruction.md</path>\n<type>file</type>\n<content>\n3: alpha\n4: beta\n\n(Showing lines 3-4 of 9. Use offset=5 to continue.)\n</content>',
            'time': {'start': 2000, 'end': 2010},
        }
        self.lines(
            'oc/trials/t1/logs/agent/trajectory.ndjson',
            [
                {
                    'type': 'step_start',
                    'timestamp': 1990,
                    'sessionID': 's',
                    'part': part('p0', 'm1', type='step-start'),
                },
                {
                    'type': 'tool_use',
                    'timestamp': 2000,
                    'sessionID': 's',
                    'part': part(
                        'p1', 'm1', type='tool', tool='read', callID='c1', state={'status': 'running', 'input': {}}
                    ),
                },
                {
                    'type': 'tool_use',
                    'timestamp': 2010,
                    'sessionID': 's',
                    'part': part('p1', 'm1', type='tool', tool='read', callID='c1', state=read_state),
                },
                {
                    'type': 'step_finish',
                    'timestamp': 2011,
                    'sessionID': 's',
                    'part': part(
                        'p2',
                        'm1',
                        type='step-finish',
                        reason='tool-calls',
                        tokens={'input': 100, 'output': 5, 'reasoning': 1, 'cache': {'read': 7}},
                    ),
                },
                {
                    'type': 'tool_use',
                    'timestamp': 2020,
                    'sessionID': 's',
                    'part': part(
                        'p3',
                        'm2',
                        type='tool',
                        tool='read',
                        callID='c2',
                        state={
                            'status': 'error',
                            'input': {'filePath': '/private/x'},
                            'error': 'The user has specified a rule which prevents you from using this specific tool call. [...]',
                        },
                    ),
                },
                {
                    'type': 'tool_use',
                    'timestamp': 2030,
                    'sessionID': 's',
                    'part': part(
                        'p4',
                        'm2',
                        type='tool',
                        tool='gui_observe',
                        callID='c3',
                        state={
                            'status': 'completed',
                            'input': {},
                            'output': 'ok',
                            'time': {'start': 2025, 'end': 2030},
                            'attachments': [
                                {'type': 'file', 'mime': 'image/png', 'url': 'data:image/png;base64,' + PNG_B64}
                            ],
                        },
                    ),
                },
                {
                    'type': 'step_finish',
                    'timestamp': 2031,
                    'sessionID': 's',
                    'part': part(
                        'p5', 'm2', type='step-finish', reason='tool-calls', tokens={'input': 200, 'output': 6}
                    ),
                },
                {
                    'type': 'text',
                    'timestamp': 9999,
                    'sessionID': 's',
                    'source': 'opencode-session-api',
                    'part': part('p6', 'm3', type='text', text='PASS', time={'start': 9990}),
                },
                {
                    'type': 'step_finish',
                    'timestamp': 9999,
                    'sessionID': 's',
                    'source': 'opencode-session-api',
                    'part': part('p7', 'm3', type='step-finish', reason='stop', tokens={'input': 1, 'output': 1}),
                },
            ],
        )
        index, reviewer, ids = self.index()
        traj = reviewer.trajectory(ids['oc'], 't1')
        read, denied, observe, text = traj['steps']
        self.assertEqual(read['source']['lines'], [2, 3], 'revisions of one part are one step')
        self.assertEqual(
            read['result']['file'],
            {
                'path': '/workspace/instruction.md',
                'content': 'alpha\nbeta',
                'first_line': 3,
                'last_line': 4,
                'note': 'Showing lines 3-4 of 9. Use offset=5 to continue.',
                'type': 'file',
            },
        )
        self.assertEqual(read['tokens']['input'], 100)
        self.assertEqual((denied['status'], denied['failure']['cause']), ('denied', 'permission_rule'))
        self.assertEqual(observe['images'][0]['sha256'], PNG_SHA)
        self.assertTrue(text['recovered'])
        self.assertIsNone(text['started_ms'], 'recovery time is never presented as original time')
        self.assertEqual(traj['stats']['tokens'], {'input': 301, 'output': 12, 'reasoning': 1, 'cached_input': 7})
        self.assertEqual(traj['end'], {'status': 'completed', 'finish_reason': 'stop', 'model_steps': 3, 'line': 9})
        self.assertTrue(any('recovered' in w for w in traj['warnings']))


class DescriptionTests(unittest.TestCase):
    def test_plain_language_actions(self):
        self.assertEqual(
            describe('gui_step', {'action': 'click', 'role': 'link', 'name': 'Edit'})[0], 'Click link “Edit”'
        )
        self.assertEqual(describe('gui_step', {'action': 'type', 'text': 'hi'})[0], 'Type “hi”')
        self.assertEqual(describe('gui_step', {'action': 'press', 'key': 'Enter'})[0], 'Press Enter')
        self.assertEqual(describe('gui_step', {'action': 'scroll', 'dx': 0, 'dy': 300})[0], 'Scroll by (0, 300)')
        self.assertEqual(
            describe('gui_observe', {'reference': 'saved'}), ('Take screenshot', 'saved as reference “saved”')
        )
        self.assertEqual(describe('gui_open_url', {'url': 'http://app:8000/'})[0], 'Open http://app:8000/')
        self.assertEqual(describe('mystery_tool', {})[0], 'Mystery tool')

    def test_failures_and_read_wrapper(self):
        self.assertEqual(parse_failure('{"cause": "policy_violation", "message": "No."}')['cause'], 'policy_violation')
        self.assertEqual(
            parse_failure("Model tried to call unavailable tool 'invalid'. Available tools: read")['cause'],
            'unavailable_tool',
        )
        self.assertEqual(
            parse_failure('something odd'), {'cause': None, 'message': 'something odd', 'raw': 'something odd'}
        )
        self.assertIsNone(read_wrapper('unrecognized <content> response'))


class VerdictTests(Fixture):
    def test_judge_and_generated_verdicts_restate_records(self):
        judge = verdict(
            {'arm': 'judge_visual'},
            [
                {
                    'id': 'a',
                    'variant': 'correct',
                    'metrics': {'status': 'graded', 'expected': 'PASS', 'prediction': 'PASS'},
                },
                {
                    'id': 'b',
                    'variant': 'faulty',
                    'metrics': {
                        'status': 'invalid_submission',
                        'reason': 'Submission is missing or malformed.',
                        'diagnostics': {'issues': [{'cause': 'missing_submission', 'impact': 'zero_credit'}]},
                    },
                },
            ],
        )
        self.assertEqual([l['tone'] for l in judge], ['good', 'bad'])
        self.assertEqual(judge[1]['cause'], 'missing_submission')
        execution = lambda variant, outcome, matched: {
            'id': variant,
            'variant': variant,
            'result': {'outcome': outcome, 'assertions': [{'matched': m} for m in matched]},
        }
        generated = verdict(
            {'arm': 'test_visual'},
            [
                {
                    'id': 't',
                    'variant': 'correct',
                    'metrics': {'status': 'graded', 'reward': 1},
                    'executions': [
                        execution('correct', 'PASS', [True, True]),
                        execution('faulty', 'BEHAVIOR_FAIL', [True, False]),
                    ],
                }
            ],
        )
        self.assertEqual(generated[-1]['text'], 'The program passed on the correct app and detected the fault.')
        self.assertIn('first mismatch at assertion #2', generated[1]['text'])

    def test_short_reasons(self):
        plan = {'arm': 'test_ui'}
        runs = lambda *o: [
            {'variant': 'correct', 'metrics': {'status': 'graded', 'executions': [{'outcome': x} for x in o]}}
        ]
        self.assertEqual(short_reason(plan, runs('PASS', 'PASS'), 'zero'), 'Fault not detected')
        self.assertEqual(short_reason(plan, runs('BEHAVIOR_FAIL', 'BEHAVIOR_FAIL'), 'zero'), 'Failed on correct app')
        errored = [
            {
                'variant': 'correct',
                'metrics': {
                    'status': 'invalid_execution',
                    'executions': [{'outcome': 'ERROR'}, {'outcome': 'ERROR'}],
                    'diagnostics': {'issues': [{'cause': 'policy_violation', 'impact': 'zero_credit'}]},
                },
            }
        ]
        self.assertEqual(short_reason(plan, errored, 'error'), 'Policy violation')
        self.assertEqual(
            short_reason(
                {'arm': 'judge_test'},
                [{'variant': 'faulty', 'metrics': {'status': 'graded', 'expected': 'FAIL', 'prediction': 'PASS'}}],
                'zero',
            ),
            'Wrong verdict on faulty state',
        )
        self.assertEqual(short_reason(plan, [], 'credited'), 'Credited')

    def test_execution_timeline_merges_acknowledgements(self):
        self.put(
            'ev/plan.json',
            {'task': 'web/x', 'arm': 'test_ui', 'planned_trials': 1, 'trials': [{'id': 't', 'variant': 'correct'}]},
        )
        self.put('ev/trials/t/verification/plan.json', {'executions': [{'id': 'e1', 'variant': 'correct'}]})
        self.lines(
            'ev/trials/t/verification/executions/e1/browser.log',
            [
                {'environment_event': 'reset', 'status': 'ready'},
                {'action': {'operation': 'step', 'arguments': {'action': 'click', 'x': 1, 'y': 2}}},
                {'operation': 'step', 'denied': False},
                {
                    'assertion': {
                        'kind': 'ui',
                        'query': {'role': 'button', 'name': 'Save'},
                        'condition': 'visible',
                        'expected': True,
                        'precondition': True,
                    },
                    'matched': False,
                },
                {'operation': 'assert', 'denied': True},
                {
                    'operation_failed': True,
                    'failure': {'cause': 'invalid_arguments', 'message': 'Arguments do not match.'},
                },
            ],
        )
        index, _, ids = self.index()
        rows = execution_timeline(index, ids['ev'], 'trials/t/verification/executions/e1/browser.log')
        self.assertEqual([r['kind'] for r in rows], ['environment', 'action', 'assertion', 'failure'])
        self.assertEqual(rows[1]['text'], 'Click at (1, 2)')
        self.assertEqual(
            (rows[2]['text'], rows[2]['status'], rows[2]['precondition']), ('button “Save” is visible', 'denied', True)
        )
        self.assertEqual(rows[3]['cause'], 'invalid_arguments')


class OverviewTests(Fixture):
    def native_run(self, attempt_status, child_status, lineage):
        spec = {'identifier': 'codex/m', 'runner': 'codex'}
        self.put(
            'group/run.json',
            {
                'schema': 'run-v1',
                'name': 'Live',
                'resolved_plan_sha256': 'abc',
                'cells': [
                    {
                        'task': 'web/x',
                        'arm': 'judge_visual',
                        'model': 'codex/m',
                        'agent_spec': spec,
                        'configuration_sha256': 'cfg',
                        'attempts': [{'path': 'evaluations/0000/attempt-1', 'status': attempt_status}],
                    },
                    {
                        'task': 'web/x',
                        'arm': 'test_ui',
                        'model': 'codex/m',
                        'agent_spec': spec,
                        'configuration_sha256': 'cfg',
                        'attempts': [],
                    },
                ],
            },
        )
        plan = {
            'task': 'web/x',
            'arm': 'judge_visual',
            'model': 'codex/m',
            'runner': 'codex',
            'agent_spec': spec,
            'configuration_sha256': 'cfg',
            'planned_trials': 1,
            'trials': [{'id': 't', 'variant': 'correct'}],
        }
        if lineage:
            plan['parent_resolved_plan_sha256'] = lineage
        self.put('group/evaluations/0000/attempt-1/e/plan.json', plan)
        self.put('group/evaluations/0000/attempt-1/e/summary.json', {'status': child_status, 'paired_score': 0})

    def test_live_attempt_links_provisionally_until_lineage_is_attested(self):
        self.native_run('running', 'running', None)
        index, reviewer, _ = self.index()
        run = next(r for r in index.hierarchy()['runs'] if r['kind'] == 'run')
        overview = reviewer.run_overview(run['id'])
        live, unstarted = overview['cells']
        self.assertEqual((live['outcome'], live['lineage']), ('running', 'pending'))
        self.assertIsNotNone(live['evaluation'])
        self.assertEqual((unstarted['outcome'], unstarted['reason']), ('missing', 'Not started'))

    def test_finished_attempt_without_lineage_is_not_linked(self):
        self.native_run('complete', 'complete', None)
        index, reviewer, _ = self.index()
        run = next(r for r in index.hierarchy()['runs'] if r['kind'] == 'run')
        self.assertIsNone(reviewer.run_overview(run['id'])['cells'][0]['evaluation'])

    def test_attested_attempt_links_and_audit_is_found(self):
        self.native_run('complete', 'complete', 'abc')
        self.put(
            'audits.json',
            {
                'schema': 'evaluation-audits-v1',
                'results': [
                    {
                        'evaluation': 'runs/x/group/evaluations/0000/attempt-1/e',
                        'returncode': 1,
                        'stdout': json.dumps({'status': 'fail', 'reason': 'not qualified'}),
                    }
                ],
            },
        )
        index, reviewer, ids = self.index()
        run = next(r for r in index.hierarchy()['runs'] if r['kind'] == 'run')
        cell = reviewer.run_overview(run['id'])['cells'][0]
        self.assertIsNone(cell['lineage'])
        review = reviewer.evaluation(cell['evaluation'])
        self.assertEqual((review['audit']['status'], review['audit']['reason']), ('fail', 'not qualified'))
        audit_check = next(c for c in review['integrity'] if c['label'] == 'Recorded boundary audit')
        self.assertEqual(audit_check['status'], 'fail')


class ServingTests(Fixture):
    def test_static_assets_are_a_closed_set(self):
        self.assertTrue(static_file('/js/main.js').is_file())
        self.assertTrue(static_file('/style.css').is_file())
        self.assertTrue(static_file('/app.js').is_file())
        for bad in (
            '/js/../server.py',
            '/../server.py',
            '/js/main.py',
            '/review.py',
            '/js/sub/x.js',
            '/JS/main.js',
            '/js/.hidden.js',
        ):
            self.assertIsNone(static_file(bad), bad)

    def test_review_endpoints_are_read_only_and_bounded(self):
        self.put(
            'ev/plan.json',
            {
                'task': 'web/x',
                'arm': 'judge_visual',
                'planned_trials': 1,
                'trials': [{'id': 't', 'variant': 'correct'}],
            },
        )
        self.lines(
            'ev/trials/t/logs/agent/trajectory.ndjson',
            [
                {
                    'type': 'text',
                    'part': {
                        'id': 'p',
                        'messageID': 'm',
                        'type': 'text',
                        'text': 'see data:image/png;base64,' + PNG_B64,
                    },
                }
            ],
        )
        server = ViewerServer(self.root, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        rid = server.index.listing()['runs'][0]['id']

        def get(path):
            connection = HTTPConnection(*server.server_address)
            connection.request('GET', path)
            response = connection.getresponse()
            body = response.read()
            connection.close()
            return response.status, response.getheader('Content-Type'), body

        status, mime, body = get('/api/evaluation?' + urlencode({'id': rid}))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['arm']['label'], 'Visual judge')
        status, _, body = get('/api/trajectory?' + urlencode({'id': rid, 'trial': 't'}))
        self.assertEqual(
            json.loads(body)['steps'][0]['text'], 'see [embedded image: available in observations and original source]'
        )
        self.assertEqual(get('/api/trajectory?' + urlencode({'id': rid, 'trial': '../t'}))[0], 400)
        self.assertEqual(get('/api/trajectory?' + urlencode({'id': rid, 'trial': 'missing'}))[0], 404)
        status, _, body = get(
            '/api/record?' + urlencode({'id': rid, 'path': 'trials/t/logs/agent/trajectory.ndjson', 'line': 1})
        )
        self.assertEqual(status, 200)
        self.assertNotIn(PNG_B64, body.decode())
        self.assertEqual(get('/api/record?' + urlencode({'id': rid, 'path': 'plan.json', 'line': 1}))[0], 400)
        self.assertEqual(
            get('/api/record?' + urlencode({'id': rid, 'path': 'trials/t/gold/x.ndjson', 'line': 1}))[0], 400
        )
        status, mime, _ = get('/js/main.js')
        self.assertEqual((status, mime), (200, 'text/javascript; charset=utf-8'))
        self.assertEqual(get('/api/overview?run=nope')[0], 404)


if __name__ == '__main__':
    unittest.main()
