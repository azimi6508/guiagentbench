import base64
import json
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from gui_agent_bench.budgets import codex_budget
from gui_agent_bench.codex_diagnostics import Usage, error_cause
from gui_agent_bench.failures import Failure
from gui_agent_bench.runners.codex_protocol import Driver, EXPECTED_FEATURE_NOTICE


@unittest.skipUnless(importlib.util.find_spec('jsonschema'), 'Codex extra required')
class ProtocolTests(unittest.TestCase):
    def driver(self, frames=(), tail=b''):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        data = b''.join(json.dumps(v).encode() + b'\n' for v in frames) + tail
        # A real pipe exercises incremental framing and concurrent stderr drain.
        script = (
            'import sys,time;sys.stdin.buffer.readline();sys.stderr.buffer.write(b"fixture diagnostic\\n");sys.stderr.flush();sys.stdout.buffer.write('
            + repr(data)
            + ');sys.stdout.flush();time.sleep(2)'
        )
        process = subprocess.Popen(
            [sys.executable, '-c', script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        def stop():
            if process.poll() is None:
                process.kill()
            process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

        self.addCleanup(stop)
        driver = Driver(process, Path(temp.name), codex_budget('judge_visual', 30))
        self.addCleanup(driver.close)
        return driver

    def state_driver(self):
        return self.driver()

    def test_reply_correlation_and_stderr(self):
        d = self.driver([{'id': 1, 'result': {'ok': True}}])
        result = d.request('initialize', {'clientInfo': {'name': 'fixture', 'version': '1'}}, time.monotonic() + 2)
        self.assertEqual(result, {'ok': True})
        deadline = time.monotonic() + 1
        while not (d.log / 'codex-stderr.log').exists() and time.monotonic() < deadline:
            d.pump(deadline)
        self.assertTrue((d.log / 'codex-stderr.log').exists())

    def test_duplicate_keys_rejected(self):
        d = self.driver(tail=b'{"id":1,"id":1,"result":{}}\n')
        with self.assertRaises(Failure):
            d.request('initialize', {'clientInfo': {'name': 'fixture', 'version': '1'}}, time.monotonic() + 2)

    def test_unmatched_reply_rejected(self):
        d = self.driver([{'id': 3, 'result': {}}])
        with self.assertRaises(Failure):
            d.request('initialize', {'clientInfo': {'name': 'fixture', 'version': '1'}}, time.monotonic() + 2)

    def test_partial_frame_never_success(self):
        d = self.driver(tail=b'{"id":1,"result":{"text":"\xf0\x9f')
        with self.assertRaises(Failure):
            d.request('initialize', {'clientInfo': {'name': 'fixture', 'version': '1'}}, time.monotonic() + 0.2)

    def test_legacy_sandbox_override_rejected(self):
        d = self.state_driver()
        with self.assertRaises(Failure):
            d.request('thread/start', {'sandbox': 'read-only'}, time.monotonic() + 1)

    def test_exact_feature_notice_only(self):
        d = self.state_driver()
        d.event({'method': 'warning', 'params': {'message': EXPECTED_FEATURE_NOTICE}}, 1)
        for method, message in [('warning', 'Missing model metadata'), ('configWarning', EXPECTED_FEATURE_NOTICE)]:
            with self.assertRaises(Failure):
                d.event({'method': method, 'params': {'message': message}}, 2)

    def test_capacity_event_and_failed_completion_keep_specific_safe_cause(self):
        d = self.state_driver()
        error = {'codexErrorInfo': 'serverOverloaded', 'message': 'SECRET provider body'}
        for event in (
            {'method': 'error', 'params': {'error': error, 'willRetry': False}},
            {'method': 'turn/completed', 'params': {'turn': {'id': 't', 'status': 'failed', 'error': error}}},
        ):
            with self.assertRaises(Failure) as caught:
                d.event(event, 1)
            self.assertEqual(caught.exception.cause, 'provider_capacity')
            self.assertNotIn('SECRET', str(caught.exception))
            self.assertFalse(d.completed)

    def test_mcp_startup_failure_and_unexpected_server(self):
        d = self.state_driver()
        for state in ['starting', 'ready']:
            d.event({'method': 'mcpServer/startupStatus/updated', 'params': {'name': 'bench', 'status': state}}, 1)
        for params in [
            {'name': 'bench', 'status': 'failed'},
            {'name': 'bench', 'status': 'cancelled'},
            {'name': 'unexpected', 'status': 'ready'},
            {'name': 'bench', 'status': 'ready', 'error': 'handshake failed'},
        ]:
            with self.assertRaises(Failure):
                d.event({'method': 'mcpServer/startupStatus/updated', 'params': params}, 2)

    def test_private_auth_response_not_logged(self):
        d = self.driver([{'id': 1, 'result': {'account': {'type': 'chatgpt', 'email': 'synthetic@example.invalid'}}}])
        d.request('account/read', {'refreshToken': False}, time.monotonic() + 2)
        self.assertNotIn('synthetic@example.invalid', (d.log / 'codex-rpc.ndjson').read_text())
        self.assertIn('privacy_projection', (d.log / 'codex-rpc.ndjson').read_text())

    def test_account_notification_requires_saved_chatgpt_and_is_private(self):
        d = self.driver(
            [
                {'method': 'account/updated', 'params': {'authMode': 'chatgpt', 'planType': 'pro'}},
                {'id': 1, 'result': {'ok': True}},
            ]
        )
        d.request('initialize', {'clientInfo': {'name': 'fixture', 'version': '1'}}, time.monotonic() + 2)
        self.assertNotIn('planType', (d.log / 'codex-rpc.ndjson').read_text())
        self.assertIn('privacy_projection', (d.log / 'codex-rpc.ndjson').read_text())
        for mode in [None, 'apiKey', 'chatgptAuthTokens']:
            with self.assertRaises(Failure):
                d.event({'method': 'account/updated', 'params': {'authMode': mode}}, 1)

    def test_unknown_server_request_declined(self):
        d = self.state_driver()
        sent = []
        d.send = sent.append
        with self.assertRaises(Failure):
            d.event({'id': 77, 'method': 'unknownApproval', 'params': {}}, 1)
        self.assertEqual(sent[0]['error']['code'], -32601)

    def test_user_input_never_fabricated(self):
        d = self.state_driver()
        sent = []
        d.send = sent.append
        with self.assertRaises(Failure):
            d.event({'id': 77, 'method': 'item/tool/requestUserInput', 'params': {}}, 1)
        self.assertEqual(sent[0]['result'], {'answers': {}})

    def test_terminal_items_not_loaded(self):
        d = self.state_driver()
        d.thread_id = 'thread'
        d.turn_id = 'turn'
        d.event(
            {
                'method': 'turn/completed',
                'params': {
                    'threadId': 'thread',
                    'turn': {'id': 'turn', 'status': 'completed', 'error': None, 'items': [], 'itemsView': 'notLoaded'},
                },
            },
            1,
        )
        self.assertTrue(d.completed)

    def test_artifact_cannot_hide_failed_terminal(self):
        d = self.state_driver()
        (d.log / 'judgment.json').write_text('{"verdict":"PASS"}')
        with self.assertRaises(Failure):
            d.event(
                {
                    'method': 'turn/completed',
                    'params': {
                        'turn': {'id': 't', 'status': 'failed', 'error': {'codexErrorInfo': 'usageLimitExceeded'}}
                    },
                },
                1,
            )
        self.assertFalse(d.completed)

    def test_unresolved_tool_fails_completion(self):
        d = self.state_driver()
        d.event({'method': 'item/started', 'params': {'item': {'type': 'mcpToolCall', 'id': 'i'}}}, 1)
        with self.assertRaises(Failure):
            d.event(
                {'method': 'turn/completed', 'params': {'turn': {'id': 't', 'status': 'completed', 'error': None}}}, 2
            )

    def test_trusted_hook_policy_feedback_distinguishes_model_from_hook_errors(self):
        d = self.state_driver()
        run = dict(id='h', eventName='preToolUse', source='system', sourcePath='/opt/bench/hooks', status='blocked')
        for text, cause in [
            ('bench-hook-v1: tool_denied:exec_command', 'policy_violation'),
            ('bench-hook-v1: hook_configuration_error', 'capability_unavailable'),
            ('Capability not permitted.', 'capability_unavailable'),
        ]:
            with self.assertRaises(Failure) as caught:
                d.event(
                    {
                        'method': 'hook/completed',
                        'params': {'run': dict(run, entries=[dict(kind='feedback', text=text)])},
                    },
                    1,
                )
            self.assertEqual(caught.exception.cause, cause)

    def test_turn_receives_complete_public_instruction_without_file_read(self):
        d = self.state_driver()
        d.thread_id = 't'
        d.completed = True
        d.tail = b''
        sent = []
        d.request = lambda method, params, deadline: sent.append(params) or {'turn': {'id': 'turn'}}
        instruction = 'Required artifact: /workspace/output/oracle.py\n' + 'x' * 17000
        d.turn('model', 'medium', 60, instruction=instruction)
        self.assertTrue(sent[0]['input'][0]['text'].endswith(instruction))
        self.assertIn('read_mcp_resource', sent[0]['input'][0]['text'])
        self.assertIn('helpers are forbidden', sent[0]['input'][0]['text'])
        with self.assertRaises(Failure):
            d.turn('model', 'medium', 60, instruction='x' * 65537)

    def test_tool_revision_count_once(self):
        d = self.state_driver()
        for method in ['item/started', 'item/completed']:
            d.event({'method': method, 'params': {'item': {'type': 'mcpToolCall', 'id': 'i'}}}, 1)
        self.assertEqual(d.tool_items, 1)
        with self.assertRaises(Failure):
            d.event({'method': 'item/completed', 'params': {'item': {'type': 'mcpToolCall', 'id': 'i'}}}, 1)

    def test_reroute_compaction_unknown_event(self):
        for method in ['model/rerouted', 'thread/compacted', 'unknown/change']:
            with self.subTest(method=method), self.assertRaises(Failure):
                self.state_driver().event({'method': method, 'params': {}}, 1)

    def test_pinned_moderation_metadata_is_evidence_not_completion(self):
        d = self.state_driver()
        d.thread_id = 'thread'
        d.turn_id = 'turn'
        params = {'threadId': 'thread', 'turnId': 'turn', 'metadata': {'synthetic': True}}
        d.event({'method': 'turn/moderationMetadata', 'params': params}, 1)
        self.assertFalse(d.completed)
        self.assertEqual(d.tool_items, 0)
        d.event({'method': 'item/started', 'params': {'item': {'type': 'mcpToolCall', 'id': 'pending'}}}, 2)
        d.event({'method': 'turn/moderationMetadata', 'params': params}, 3)
        with self.assertRaises(Failure):
            d.event(
                {'method': 'turn/completed', 'params': {'turn': {'id': 'turn', 'status': 'completed', 'error': None}}},
                4,
            )

    def test_moderation_metadata_requires_current_turn_and_exact_envelope(self):
        params = {'threadId': 'thread', 'turnId': 'turn', 'metadata': None}
        d = self.state_driver()
        with self.assertRaises(Failure):
            d.event({'method': 'turn/moderationMetadata', 'params': params}, 1)
        d.thread_id = 'thread'
        d.turn_id = 'turn'
        bad = [
            {k: v for k, v in params.items() if k != 'metadata'},
            dict(params, threadId='other'),
            dict(params, turnId='other'),
            dict(params, tool='unexpected'),
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(Failure):
                d.event({'method': 'turn/moderationMetadata', 'params': value}, 2)

    def test_moderation_metadata_retains_raw_evidence(self):
        event = {
            'method': 'turn/moderationMetadata',
            'params': {'threadId': 'thread', 'turnId': 'turn', 'metadata': {'synthetic': 'retained-metadata-evidence'}},
        }
        d = self.driver([event, {'id': 1, 'result': {'ok': True}}])
        d.thread_id = 'thread'
        d.turn_id = 'turn'
        self.assertEqual(
            d.request('initialize', {'clientInfo': {'name': 'fixture', 'version': '1'}}, time.monotonic() + 2),
            {'ok': True},
        )
        rows = [json.loads(line) for line in (d.log / 'codex-rpc.ndjson').read_text().splitlines()]
        incoming = [
            json.loads(base64.b64decode(row['frame_base64']))
            for row in rows
            if row.get('direction') == 'in' and row.get('frame_base64')
        ]
        self.assertIn(event, incoming)
        self.assertFalse(d.completed)

    def test_secret_sentinel_stops_logging(self):
        d = self.state_driver()
        d.secrets = (b'SENTINEL_CREDENTIAL',)
        with self.assertRaises(Failure):
            d._write_log('codex-stderr.log', b'SENTINEL_CREDENTIAL')
        self.assertNotIn('SENTINEL_CREDENTIAL', (d.log / 'codex-stderr.log').read_text())


class DiagnosticTests(unittest.TestCase):
    def test_typed_errors(self):
        for value, cause in [
            ('usageLimitExceeded', 'provider_rate_limit'),
            ('contextWindowExceeded', 'context_overflow'),
            ({'httpConnectionFailed': {'httpStatusCode': 401}}, 'provider_transport_error'),
            ('madeUp', 'provider_error'),
            ({'unexpected': {}}, 'provider_error'),
        ]:
            self.assertEqual(error_cause(value), cause)
        self.assertEqual(error_cause('unauthorized', startup=True), 'capability_unavailable')

    def test_cumulative_usage_not_summed(self):
        usage = Usage()
        self.assertIsNone(usage.record()['usage'])
        self.assertFalse(usage.record()['usage_complete'])
        value = {
            'total': {
                'inputTokens': 100,
                'cachedInputTokens': 20,
                'outputTokens': 50,
                'reasoningOutputTokens': 10,
                'totalTokens': 150,
            }
        }
        usage.update(value)
        usage.update(value)
        self.assertEqual(usage.record()['usage']['totalTokens'], 150)
        self.assertIsNone(usage.record()['provider_cost_usd'])
        with self.assertRaises(Failure):
            usage.update({'total': {'inputTokens': 1}})
