"""Real local relay HTTP exchanges; no external provider or real credential."""

from contextlib import redirect_stdout
from http.client import HTTPConnection, IncompleteRead
from io import BytesIO, StringIO
import json
from pathlib import Path
import socket
import ssl
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from test_failures import provider_server
from gui_agent_bench import gateway
from gui_agent_bench.failures import Failure, issue, record_issues, diagnostics, summarize
from gui_agent_bench.inference_diagnostics import ERROR_BODY_LIMIT, error_summary, inspect_response, usage_summary


class Response(BytesIO):
    status = 200

    def __init__(self, data, content_type='text/event-stream'):
        super().__init__(data)
        self.headers = {'Content-Type': content_type, 'X-Secret': 'TEST_SENTINEL'}


def event(value):
    return b'data: ' + json.dumps(value).encode() + b'\n\n'


class InferenceDiagnosticTests(unittest.TestCase):
    def exchange(self, upstream, *, stream=True, extra=None):
        output, calls = StringIO(), []

        def reply(request, timeout):
            calls.append(request)
            if isinstance(upstream, Exception):
                raise upstream
            return upstream

        payload = {'model': 'model', 'messages': [{'role': 'user', 'content': 'PRIVATE_PROMPT'}], 'stream': stream}
        payload.update(extra or {})
        with redirect_stdout(output), provider_server(reply) as address:
            connection = HTTPConnection(*address, timeout=3)
            connection.request(
                'POST', '/v1/chat/completions', json.dumps(payload), {'Content-Type': 'application/json'}
            )
            response = connection.getresponse()
            status, headers, body = response.status, dict(response.getheaders()), response.read()
            connection.close()
        records = list(map(json.loads, output.getvalue().splitlines()))
        self.assertNotIn('TEST_SENTINEL', output.getvalue() + body.decode())
        self.assertNotIn('PRIVATE_PROMPT', output.getvalue())
        self.assertNotIn('X-Secret', headers)
        self.assertEqual(len(calls), 1)  # No retries, even on transient failures.
        return status, body, records, calls

    def failure(self, records):
        failed = [r['failure'] for r in records if 'failure' in r]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]['impact'], 'feedback')
        return failed[0]['inference']

    def test_http_status_and_typed_error_survive_without_raw_body_or_headers(self):
        for code, kind in [
            (400, 'invalid_request'),
            (401, 'authentication'),
            (402, 'payment_required'),
            (403, 'permission_denied'),
            (429, 'rate_limit_exceeded'),
            (500, 'server'),
            (502, 'provider_unavailable'),
            (503, 'provider_overloaded'),
        ]:
            data = {
                'error': {
                    'code': code,
                    'message': 'TEST_SENTINEL PRIVATE_PROMPT',
                    'metadata': {
                        'error_type': kind,
                        'raw': 'TEST_SENTINEL',
                        'provider_name': 'TEST_SENTINEL',
                        'provider_code': 'TEST_SENTINEL',
                    },
                },
                'request_id': 'TEST_SENTINEL',
            }
            error = urllib.error.HTTPError(
                'https://TEST_SENTINEL',
                code,
                'TEST_SENTINEL',
                {'Authorization': 'TEST_SENTINEL'},
                BytesIO(json.dumps(data).encode()),
            )
            with self.subTest(code=code):
                status, _, records, _ = self.exchange(error)
                info = self.failure(records)
                self.assertEqual(status, code)
                self.assertEqual(
                    (info['stage'], info['upstream_status'], info['error_type'], info['error_code']),
                    ('upstream_http', code, kind, code),
                )
                self.assertFalse(info['stream_started'])
                self.assertEqual(info['error_body'], 'structured')

    def test_unknown_and_encoded_error_fields_are_not_copied(self):
        for raw in ('TEST_SENTINEL', 'TEST%5FSENTINEL', {'key': 'TEST_SENTINEL'}, ['TEST_SENTINEL']):
            with self.subTest(raw=raw):
                self.assertEqual(
                    error_summary({'code': raw, 'metadata': {'error_type': raw}}),
                    {'error_code': 'unknown', 'error_type': 'unknown'},
                )
        self.assertEqual(
            error_summary({'code': 'server_error'}), {'error_code': 'server_error', 'error_type': 'unknown'}
        )
        self.assertEqual(error_summary({'code': True}), {'error_code': 'unknown', 'error_type': 'unknown'})

    def test_missing_malformed_and_oversized_error_bodies_keep_status(self):
        for data, expected in [
            (b'', 'empty'),
            (b'TEST_SENTINEL invalid JSON', 'unavailable_or_invalid'),
            (b'"TEST_SENTINEL"', 'unrecognized'),
            (b'x' * (ERROR_BODY_LIMIT + 1), 'oversized'),
        ]:
            with self.subTest(expected=expected):
                error = urllib.error.HTTPError('https://TEST_SENTINEL', 503, 'TEST_SENTINEL', {}, BytesIO(data))
                _, _, records, _ = self.exchange(error)
                info = self.failure(records)
                self.assertEqual(info['upstream_status'], 503)
                self.assertEqual(info['error_body'], expected)

    def test_transport_failures_are_attributed_to_connection_stage(self):
        for error, cause, reason in [
            (TimeoutError('TEST_SENTINEL'), 'provider_timeout', 'timeout'),
            (urllib.error.URLError(TimeoutError('TEST_SENTINEL')), 'provider_timeout', 'timeout'),
            (urllib.error.URLError('TEST_SENTINEL'), 'provider_transport_error', 'connection_failed'),
            (IncompleteRead(b'TEST_SENTINEL'), 'provider_transport_error', 'connection_failed'),
        ]:
            with self.subTest(cause=cause):
                _, _, records, _ = self.exchange(error)
                info = self.failure(records)
                self.assertEqual((info['stage'], info['reason']), ('upstream_connect', reason))
                self.assertNotIn('upstream_status', info)
                self.assertEqual([r['failure']['cause'] for r in records if 'failure' in r], [cause])

    def test_valid_stream_is_unchanged_and_usage_is_numeric_only(self):
        chunks = [
            b': OPENROUTER PROCESSING\r\n\r\n',
            event({'choices': [{'delta': {'content': 'hello'}, 'finish_reason': None}]}),
            event(
                {
                    'choices': [{'delta': {}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 7, 'completion_tokens': 3, 'total_tokens': 10, 'cost': 0.001},
                }
            ),
            b'data: [DONE]\n\n',
        ]
        wire = b''.join(chunks)
        status, body, records, _ = self.exchange(Response(wire))
        self.assertEqual((status, body), (200, wire))
        self.assertFalse(any('failure' in r for r in records))
        info = records[-1]['inference']
        self.assertEqual(
            (info['stage'], info['response_bytes'], info['finish_reasons']), ('complete', len(wire), ['stop'])
        )
        self.assertTrue(info['completion_seen'])
        self.assertEqual([r['usage']['cost'] for r in records if 'usage' in r], [0.001])

    def test_multiline_sse_and_usage_only_accounting_frames(self):
        wire = (
            b'data: {"choices":\r\ndata: [{"finish_reason":"tool_calls","delta":{}}]}\r\n\r\n'
            + event({'choices': [], 'usage': {'total_tokens': 10}})
            + b'data: [DONE]\n\n'
        )
        _, body, records, _ = self.exchange(Response(wire))
        self.assertEqual(body, wire)
        self.assertEqual(records[-1]['inference']['finish_reasons'], ['tool_calls'])

    def test_sse_error_under_http_200_is_safely_replaced(self):
        first = event({'choices': [{'delta': {'content': 'partial'}, 'finish_reason': None}]})
        bad = event(
            {
                'error': {
                    'code': 429,
                    'message': 'TEST_SENTINEL',
                    'metadata': {'error_type': 'rate_limit_exceeded', 'raw': 'TEST_SENTINEL'},
                },
                'id': 'TEST_SENTINEL',
                'choices': [{'finish_reason': 'error'}],
            }
        )
        for prefix in (b'', first):
            with self.subTest(partial=bool(prefix)):
                status, body, records, _ = self.exchange(Response(prefix + bad + b'data: [DONE]\n\n'))
                info = self.failure(records)
                self.assertEqual((status, info['upstream_status'], info['error_code']), (200, 200, 429))
                self.assertEqual(info['stage'], 'upstream_stream')
                self.assertTrue(body.startswith(prefix))
                self.assertIn(b'The inference provider reported a rate limit.', body)
                self.assertNotIn(b'[DONE]', body)
                self.assertFalse(info['completion_seen'])

    def test_finish_reason_error_without_error_envelope_is_failure(self):
        _, _, records, _ = self.exchange(Response(event({'choices': [{'finish_reason': 'error', 'delta': {}}]})))
        self.assertEqual(self.failure(records)['stage'], 'upstream_stream')

    def test_stream_error_keeps_only_allowlisted_native_finish_reason(self):
        cases = [
            (
                {'finish_reason': 'error', 'native_finish_reason': 'MALFORMED_FUNCTION_CALL'},
                'MALFORMED_FUNCTION_CALL',
                False,
            ),
            ({'finish_reason': 'error', 'native_finish_reason': 'TEST_SENTINEL'}, 'unknown', False),
            ({'finish_reason': 'error'}, None, False),
            (
                {
                    'error': {'code': 502, 'message': 'TEST_SENTINEL'},
                    'finish_reason': 'error',
                    'native_finish_reason': 'other',
                },
                'OTHER',
                True,
            ),
        ]
        for choice, native, envelope in cases:
            with self.subTest(choice=choice):
                _, _, records, _ = self.exchange(Response(event({'choices': [{'index': 0, 'delta': {}, **choice}]})))
                info = self.failure(records)
                self.assertEqual((info.get('native_finish_reason'), info['error_envelope']), (native, envelope))

    def test_named_error_events_never_forward_unstructured_text(self):
        for data in (b'TEST_SENTINEL', b'{"message":"TEST_SENTINEL"}'):
            with self.subTest(data=data):
                _, _, records, _ = self.exchange(Response(b'event: error\ndata: ' + data + b'\n\n'))
                self.assertEqual(self.failure(records)['stage'], 'upstream_stream')

    def test_http_200_json_errors_top_level_and_nested_are_not_forwarded(self):
        error = {'code': 400, 'message': 'TEST_SENTINEL', 'metadata': {'error_type': 'context_length_exceeded'}}
        for envelope in (
            {'error': error},
            {'choices': [{'message': {'content': 'TEST_SENTINEL'}, 'error': error, 'finish_reason': 'error'}]},
        ):
            with self.subTest(envelope=envelope):
                status, _, records, _ = self.exchange(
                    Response(json.dumps(envelope).encode(), 'application/json'), stream=False
                )
                info = self.failure(records)
                self.assertEqual(status, 502)
                self.assertEqual(
                    (info['stage'], info['upstream_status'], info['error_type']),
                    ('upstream_json', 200, 'context_length_exceeded'),
                )
                self.assertFalse(info['stream_started'])

    def test_valid_nonstream_json_is_unchanged(self):
        wire = json.dumps(
            {
                'choices': [{'message': {'content': 'hello'}, 'finish_reason': 'stop'}],
                'usage': {'total_tokens': 10, 'cost': 0.01},
            }
        ).encode()
        status, body, records, _ = self.exchange(Response(wire, 'application/json; charset=utf-8'), stream=False)
        self.assertEqual((status, body), (200, wire))
        self.assertEqual(records[-1]['inference']['stage'], 'complete')

    def test_unexpected_eof_and_partial_events_fail_closed(self):
        for wire in (
            b'',
            event({'choices': [{'delta': {'content': 'partial'}}]}),
            b'data: {"error":{"message":"TEST_SENTINEL"}}',
        ):
            with self.subTest(wire=wire):
                _, _, records, _ = self.exchange(Response(wire))
                self.assertEqual(self.failure(records)['reason'], 'incomplete_stream')

    def test_protocol_failure_does_not_forward_malformed_json(self):
        for wire, format in [
            (b'data: TEST_SENTINEL\n\n', 'text/event-stream'),
            (b'TEST_SENTINEL', 'application/json'),
            (b'TEST_SENTINEL', 'text/html'),
        ]:
            with self.subTest(format=format):
                _, _, records, _ = self.exchange(Response(wire, format))
                self.assertEqual(self.failure(records)['stage'], 'response_protocol')

    def test_read_failure_is_not_mislabeled_as_initial_connection_failure(self):
        class Broken(Response):
            def readline(self, size=-1):
                raise TimeoutError('TEST_SENTINEL')

        _, _, records, _ = self.exchange(Broken(b''))
        self.assertEqual(
            (self.failure(records)['stage'], self.failure(records)['reason']), ('upstream_read', 'timeout')
        )

    def test_downstream_disconnect_is_not_attributed_to_upstream(self):
        original = gateway.BaseHTTPRequestHandler.end_headers

        def disconnected(handler):
            original(handler)

            class BrokenWriter:
                closed = False

                def write(self, data):
                    raise BrokenPipeError('TEST_SENTINEL')

                def flush(self):
                    pass

                def close(self):
                    pass

            handler.wfile = BrokenWriter()

        with patch.object(gateway.BaseHTTPRequestHandler, 'end_headers', disconnected):
            _, _, records, _ = self.exchange(Response(event({'choices': []}) + b'data: [DONE]\n\n'))
        self.assertEqual(self.failure(records)['stage'], 'downstream_write')

    def test_response_limit_remains_a_failure_not_partial_success(self):
        with patch.object(gateway, 'RESPONSE_LIMIT', 32):
            _, _, records, _ = self.exchange(Response(b'data: ' + b'x' * 100 + b'\n\n'))
        self.assertEqual(self.failure(records)['reason'], 'response_limit')
        self.assertEqual([r['failure']['cause'] for r in records if 'failure' in r], ['evidence_overflow'])

    def test_accounting_rejects_arbitrary_text_and_nonfinite_numbers(self):
        for value in ('TEST_SENTINEL', {'secret': 'TEST_SENTINEL'}, True, float('nan'), float('inf'), -1, 1e20):
            with self.subTest(value=value):
                self.assertEqual(
                    usage_summary(
                        {
                            'usage': {
                                'prompt_tokens': value,
                                'completion_tokens': value,
                                'total_tokens': value,
                                'cost': value,
                            }
                        }
                    ),
                    dict.fromkeys(('prompt_tokens', 'completion_tokens', 'total_tokens', 'cost')),
                )
        _, _, records, _ = self.exchange(
            Response(event({'choices': [], 'usage': {'cost': 'TEST_SENTINEL'}}) + b'data: [DONE]\n\n')
        )
        self.assertEqual(self.failure(records)['reason'], 'credential_echo')
        self.assertFalse(any('usage' in r for r in records))

    def test_request_summary_omits_content_tool_names_and_debug_echo(self):
        wire = event({'choices': [{'finish_reason': 'stop'}]}) + b'data: [DONE]\n\n'
        _, _, records, calls = self.exchange(
            Response(wire),
            extra={
                'tools': [{'type': 'function', 'function': {'name': 'PRIVATE_PROMPT'}}],
                'tool_choice': {'type': 'function', 'function': {'name': 'PRIVATE_PROMPT'}},
                'debug': {'echo_upstream_body': True},
            },
        )
        info = next(r['inference'] for r in records if r.get('event') == 'inference_request')
        self.assertEqual(
            (info['message_count'], info['tool_count'], info['tool_choice'], info['max_tokens']),
            (1, 1, 'function', 4096),
        )
        self.assertNotIn('debug', json.loads(calls[0].data))
        self.assertEqual(json.loads(calls[0].data)['transforms'], [])

    def test_diagnostics_survive_rollup_without_changing_impact_or_denominator(self):
        _, _, records, _ = self.exchange(urllib.error.HTTPError('http://private', 503, 'TEST_SENTINEL', {}, None))
        issues = record_issues(records, phase='inference', source='logs/provider.ndjson')
        self.assertEqual(issues[0]['inference']['upstream_status'], 503)
        self.assertEqual(issues[0]['source']['file'], 'logs/provider.ndjson')
        report = summarize([{'reward': 0, 'diagnostics': diagnostics(issues)}], 3)
        self.assertEqual(report['planned_units'], 3)
        self.assertFalse(report['automatic_retries'])
        old = record_issues(
            [{'failure': {k: v for k, v in issues[0].items() if k not in ('source', 'inference')}}],
            phase='inference',
            source='logs/provider.ndjson',
        )
        self.assertNotIn('inference', old[0])  # No invented historical status.

    def test_response_shapes_are_checked_without_message_based_guessing(self):
        for value in ('TEST_SENTINEL', [], {'choices': 'TEST_SENTINEL'}, {'choices': ['TEST_SENTINEL']}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                inspect_response(value)
        self.assertEqual(inspect_response({'choices': [{'finish_reason': 'TEST_SENTINEL'}]}), (None, ['unknown']))

    def test_exact_credential_echo_in_success_fields_or_comments_is_blocked(self):
        for wire in (
            event({'choices': [{'delta': {'content': 'TEST_SENTINEL'}}]}),
            b': TEST_SENTINEL\n\n',
            b'data: {"choices":[{"delta":{"content":"TEST\\u005fSENTINEL"}}]}\n\n',
        ):
            with self.subTest(wire=wire):
                _, _, records, _ = self.exchange(Response(wire + b'data: [DONE]\n\n'))
                self.assertEqual(self.failure(records)['reason'], 'credential_echo')

    def test_unfamiliar_exception_never_reaches_httpserver_traceback(self):
        _, _, records, _ = self.exchange(RuntimeError('TEST_SENTINEL PRIVATE_PROMPT'))
        self.assertEqual(self.failure(records)['reason'], 'unclassified_relay_error')

    def test_invalid_request_is_local_not_an_upstream_failure(self):
        output = StringIO()
        calls = []

        def forbidden(*args, **kwargs):
            calls.append(True)
            raise AssertionError('Upstream must not be called')

        with redirect_stdout(output), provider_server(forbidden) as address:
            for payload in (
                [],
                {'model': 'wrong', 'messages': []},
                {'model': 'model', 'messages': [], 'tools': ['invalid']},
            ):
                connection = HTTPConnection(*address, timeout=3)
                connection.request('POST', '/v1/chat/completions', json.dumps(payload))
                response = connection.getresponse()
                self.assertIn(response.status, (400, 403))
                response.read()
                connection.close()
        self.assertEqual(calls, [])
        for record in map(json.loads, output.getvalue().splitlines()):
            self.assertEqual(record['failure']['inference']['stage'], 'relay_request')
            self.assertFalse(record['failure']['inference']['upstream_request_sent'])

    def test_local_request_budget_is_not_an_upstream_rate_limit(self):
        from gui_agent_bench.budgets import provider_requests

        limit = provider_requests('judge_visual')
        output = StringIO()
        calls = []

        def success(request, timeout):
            calls.append(True)
            return Response(b'data: [DONE]\n\n')

        with redirect_stdout(output), provider_server(success) as address:
            for index in range(limit + 1):
                connection = HTTPConnection(*address, timeout=3)
                connection.request(
                    'POST', '/v1/chat/completions', json.dumps({'model': 'model', 'messages': [], 'stream': True})
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 429 if index == limit else 200)
                response.read()
                connection.close()
        records = list(map(json.loads, output.getvalue().splitlines()))
        self.assertEqual(len(calls), limit)
        info = self.failure(records)
        self.assertEqual((info['stage'], info['request'], info['relay_status']), ('relay_request', limit + 1, 429))
        self.assertEqual(records[-1]['failure']['cause'], 'budget_exhausted')

    def test_dns_tls_reset_and_refusal_use_types_not_raw_exception_text(self):
        for error, reason in [
            (socket.gaierror('TEST_SENTINEL'), 'dns_failure'),
            (ssl.SSLError('TEST_SENTINEL'), 'tls_failure'),
            (ConnectionResetError('TEST_SENTINEL'), 'connection_reset'),
            (ConnectionRefusedError('TEST_SENTINEL'), 'connection_refused'),
        ]:
            with self.subTest(reason=reason):
                _, _, records, _ = self.exchange(urllib.error.URLError(error))
                self.assertEqual(self.failure(records)['reason'], reason)

    def test_pinned_max_steps_prefill_is_sent_as_user_turn_without_tools(self):
        from gui_agent_bench.runners.opencode import MAX_STEPS_NOTICE

        wire = event({'choices': [{'finish_reason': 'stop'}]}) + b'data: [DONE]\n\n'
        tools = [{'type': 'function', 'function': {'name': 'read'}}]
        history = [
            {'role': 'user', 'content': 'PRIVATE_PROMPT'},
            {
                'role': 'assistant',
                'content': None,
                'tool_calls': [{'id': 'c', 'type': 'function', 'function': {'name': 'read', 'arguments': '{}'}}],
            },
            {'role': 'tool', 'tool_call_id': 'c', 'content': 'ok'},
        ]
        for notice in (MAX_STEPS_NOTICE, [{'type': 'text', 'text': MAX_STEPS_NOTICE}]):
            with self.subTest(list_content=isinstance(notice, list)):
                _, _, records, calls = self.exchange(
                    Response(wire),
                    extra={'tools': tools, 'messages': history + [{'role': 'assistant', 'content': notice}]},
                )
                sent = json.loads(calls[0].data)
                self.assertEqual(sent['messages'][:-1], history)
                self.assertEqual(sent['messages'][-1], {'role': 'user', 'content': MAX_STEPS_NOTICE})
                self.assertEqual((sent['tools'], sent['tool_choice']), (tools, 'none'))
                info = next(r['inference'] for r in records if r.get('event') == 'inference_request')
                self.assertEqual((info['client_adaptation'], info['tool_choice']), ('final_step_notice', 'none'))

    def test_model_written_or_altered_assistant_turns_are_never_adapted(self):
        from gui_agent_bench.runners.opencode import MAX_STEPS_NOTICE

        wire = event({'choices': [{'finish_reason': 'stop'}]}) + b'data: [DONE]\n\n'
        for last in (
            {'role': 'assistant', 'content': MAX_STEPS_NOTICE + ' '},
            {'role': 'assistant', 'content': 'Model draft'},
            {'role': 'assistant', 'content': MAX_STEPS_NOTICE, 'name': 'x'},
            {'role': 'user', 'content': MAX_STEPS_NOTICE},
        ):
            with self.subTest(last=last):
                messages = [{'role': 'user', 'content': 'PRIVATE_PROMPT'}, last]
                _, _, records, calls = self.exchange(
                    Response(wire),
                    extra={'messages': messages, 'tools': [{'type': 'function', 'function': {'name': 'read'}}]},
                )
                sent = json.loads(calls[0].data)
                self.assertEqual(sent['messages'], messages)
                self.assertNotIn('tool_choice', sent)
                self.assertFalse(any('client_adaptation' in r.get('inference', {}) for r in records))

    def test_trial_controller_retains_provider_details_and_zero_credit_failure(self):
        from gui_agent_bench.trial import run_trial

        _, _, records, _ = self.exchange(urllib.error.HTTPError('http://private', 503, 'TEST_SENTINEL', {}, None))
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / 'logs').mkdir()
            (folder / 'logs/provider.ndjson').write_text(''.join(json.dumps(r) + '\n' for r in records))
            failed = {
                'status': 'trial_error',
                'reward': 0,
                'diagnostics': diagnostics(
                    [
                        issue(
                            Failure('process_error'), phase='authoring', operation='agent_process', impact='zero_credit'
                        )
                    ]
                ),
            }
            with patch('gui_agent_bench.trial._run_trial', return_value=failed):
                result = run_trial(folder, folder, folder)
            self.assertEqual((result['status'], result['reward']), ('trial_error', 0))
            saved = json.loads((folder / 'logs/verifier/metrics.json').read_text())
            provider = saved['diagnostics']['issues'][0]
            self.assertEqual((provider['inference']['request'], provider['inference']['upstream_status']), (1, 503))
            self.assertEqual(saved['diagnostics']['issues'][1]['impact'], 'zero_credit')
            self.assertNotIn('TEST_SENTINEL', json.dumps(saved))


if __name__ == '__main__':
    unittest.main()
