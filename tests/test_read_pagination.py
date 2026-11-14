"""Pinned OpenCode read pages must not disable real evidence-loss safeguards."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from gui_agent_bench.failures import Failure
from gui_agent_bench.runners.opencode import event_issues, validate_events, run

FINISH = {'type': 'step_finish', 'part': {'reason': 'stop'}}


def page_event(start=1, limit=2, total=9, lines=None):
    lines = lines if lines is not None else ['first line', 'second line']
    end = start + len(lines) - 1
    path = '/workspace/instruction.md'
    text = '\n'.join(lines)
    numbered = '\n'.join(f'{start + i}: {line}' for i, line in enumerate(lines))
    output = (
        f'<path>{path}</path>\n<type>file</type>\n<content>\n'
        f'{numbered}\n\n(Showing lines {start}-{end} of {total}. '
        f'Use offset={end + 1} to continue.)\n</content>'
    )
    return {
        'type': 'tool_use',
        'part': {
            'type': 'tool',
            'tool': 'read',
            'state': {
                'status': 'completed',
                'input': {'filePath': path, 'offset': start, 'limit': limit},
                'output': output,
                'metadata': {
                    'truncated': True,
                    'display': {
                        'type': 'file',
                        'path': path,
                        'text': text,
                        'lineStart': start,
                        'lineEnd': end,
                        'totalLines': total,
                        'truncated': True,
                    },
                },
            },
        },
    }


class ReadPaginationTests(unittest.TestCase):
    def assert_overflow(self, event):
        found = event_issues([event, FINISH])
        self.assertEqual([x['cause'] for x in found], ['evidence_overflow'])
        self.assertEqual(found[0]['source']['record_index'], 0)
        with self.assertRaises(Failure):
            validate_events([event, FINISH])

    def test_explicit_complete_page_is_not_evidence_loss(self):
        validate_events([page_event(), FINISH])
        validate_events([page_event(start=3), FINISH])

    def test_model_need_not_read_whole_file_or_every_page(self):
        # No prior full read and no following continuation are required.
        validate_events([page_event(start=5), FINISH])

    def test_end_of_file_can_return_fewer_than_requested_lines(self):
        event = page_event(start=8, limit=50, total=9)
        state = event['part']['state']
        state['metadata']['truncated'] = False
        state['metadata']['display']['truncated'] = False
        state['output'] = state['output'].replace(
            '(Showing lines 8-9 of 9. Use offset=10 to continue.)', '(End of file - total 9 lines)'
        )
        validate_events([event, FINISH])

    def test_default_offset_and_pinned_default_limit_are_supported(self):
        event = page_event(limit=2000, total=2001, lines=['x'] * 2000)
        del event['part']['state']['input']['offset']
        del event['part']['state']['input']['limit']
        validate_events([event, FINISH])

    def test_blank_unicode_and_literal_metadata_text_are_preserved(self):
        for lines in [
            ['', ''],
            ['İstanbul 🧪', 'truncated: true'],
            ['<content>', '</content>'],
            ['literal marker:', '... (line truncated to 2000 chars)'],
        ]:
            with self.subTest(lines=lines):
                validate_events([page_event(lines=lines), FINISH])

    def test_real_gemini_pages_remain_regression_fixtures(self):
        fixture = json.loads((ROOT / 'tests/fixtures/opencode-read-pages.json').read_text())
        self.assertEqual(len(fixture['events']), 2)
        for event in fixture['events']:
            with self.subTest(input=event['part']['state']['input']):
                validate_events([event, FINISH])

    def test_short_or_inconsistent_page_is_rejected(self):
        mutations = [
            lambda s: s['input'].update(limit=50),
            lambda s: s['input'].update(offset=2),
            lambda s: s['input'].update(filePath='/workspace/other.md'),
            lambda s: s['metadata']['display'].update(lineEnd=3),
            lambda s: s['metadata']['display'].update(lineStart=2),
            lambda s: s['metadata']['display'].update(totalLines=2),
            lambda s: s['metadata']['display'].update(text='first line'),
            lambda s: s.update(output=s['output'][:-10]),
            lambda s: s.update(output=s['output'].replace('1: first line', '1: altered line')),
            lambda s: s.update(output=s['output'].replace('offset=3', 'offset=4')),
        ]
        for mutation in mutations:
            event = page_event()
            mutation(event['part']['state'])
            with self.subTest(mutation=mutation):
                self.assert_overflow(event)

    def test_invalid_input_and_range_types_fail_closed(self):
        for key in ['offset', 'limit']:
            for value in [True, False, 0, -1, 2.0, '2', None]:
                event = page_event()
                event['part']['state']['input'][key] = value
                with self.subTest(key=key, value=value):
                    self.assert_overflow(event)
        for key in ['lineStart', 'lineEnd', 'totalLines']:
            for value in [True, '2', None]:
                event = page_event()
                event['part']['state']['metadata']['display'][key] = value
                with self.subTest(key=key, value=value):
                    self.assert_overflow(event)

    def test_missing_unknown_or_non_read_metadata_fails_closed(self):
        mutations = [
            lambda e: e.update(type='text'),
            lambda e: e['part'].update(tool='gui_observe'),
            lambda e: e['part']['state'].update(status='error'),
            lambda e: e['part']['state'].pop('input'),
            lambda e: e['part']['state'].pop('output'),
            lambda e: e['part']['state']['metadata'].pop('display'),
            lambda e: e['part']['state']['metadata']['display'].update(type='directory'),
            lambda e: e['part']['state']['metadata']['display'].update(truncated=False),
            lambda e: e['part']['state']['metadata'].update(truncated=False),
        ]
        for mutation in mutations:
            event = page_event()
            mutation(event)
            with self.subTest(mutation=mutation):
                self.assert_overflow(event)

    def test_real_byte_cap_is_rejected_even_if_line_range_matches(self):
        event = page_event()
        state = event['part']['state']
        state['output'] = state['output'].replace(
            '(Showing lines 1-2 of 9.', '(Output capped at 50 KB. Showing lines 1-2.'
        )
        self.assert_overflow(event)

    def test_claimed_page_above_pinned_byte_or_line_limits_is_rejected(self):
        self.assert_overflow(page_event(limit=100, lines=['x' * 1000] * 100, total=101))
        self.assert_overflow(page_event(lines=['x' * 2001, 'next']))

    def test_malformed_metadata_cannot_bypass_unknown_truncation(self):
        for target in ['input', 'metadata', 'display', 'state']:
            for value in [None, [], 'unknown']:
                event = page_event()
                if target == 'state':
                    event['part']['state'] = value
                elif target == 'display':
                    event['part']['state']['metadata']['display'] = value
                else:
                    event['part']['state'][target] = value
                event['truncated'] = True
                with self.subTest(target=target, value=value):
                    self.assert_overflow(event)

    def test_line_clipping_is_rejected_with_or_without_pagination_flags(self):
        for truncated in [True, False]:
            event = page_event(lines=['x' * 2000 + '... (line truncated to 2000 chars)', 'next'])
            if not truncated:
                state = event['part']['state']
                state['metadata']['truncated'] = False
                state['metadata']['display']['truncated'] = False
            with self.subTest(truncated=truncated):
                self.assert_overflow(event)

    def test_line_limits_follow_pinned_javascript_utf16_units(self):
        validate_events([page_event(lines=['🧪' * 1000, 'next']), FINISH])
        self.assert_overflow(page_event(lines=['🧪' * 1001, 'next']))
        event = page_event(lines=['🧪' * 1000 + '... (line truncated to 2000 chars)', 'next'])
        event['part']['state']['metadata']['truncated'] = False
        event['part']['state']['metadata']['display']['truncated'] = False
        self.assert_overflow(event)

    def test_exemption_does_not_hide_other_truncation_flags(self):
        for location in ['event', 'state', 'metadata', 'display']:
            for flag in ['truncated', 'isTruncated']:
                event = page_event()
                state = event['part']['state']
                target = {
                    'event': event,
                    'state': state,
                    'metadata': state['metadata'],
                    'display': state['metadata']['display'],
                }[location]
                if location in ['metadata', 'display'] and flag == 'truncated':
                    target['other'] = {flag: True}
                else:
                    target[flag] = True
                with self.subTest(location=location, flag=flag):
                    self.assert_overflow(event)

    def test_duplicate_flags_make_one_diagnostic_per_event(self):
        event = {
            'type': 'tool_use',
            'part': {'metadata': {'truncated': True, 'display': {'truncated': True}, 'isTruncated': True}},
        }
        self.assert_overflow(event)
        found = event_issues([event, deepcopy(event), FINISH])
        self.assertEqual(len(found), 2)
        self.assertEqual([x['source']['record_index'] for x in found], [0, 1])

    def test_pagination_does_not_hide_compaction_length_or_missing_stop(self):
        for extra, cause in [
            ({'type': 'compaction'}, 'context_overflow'),
            ({'type': 'step_finish', 'part': {'reason': 'length'}}, 'context_overflow'),
            ({'type': 'error'}, 'unknown_operation_error'),
        ]:
            found = event_issues([page_event(), extra, FINISH])
            self.assertEqual([x['cause'] for x in found], [cause])
        self.assertEqual([x['cause'] for x in event_issues([page_event()])], ['incomplete_trajectory'])

    def test_runner_accepts_page_but_rejects_real_overflow_and_keeps_raw_log(self):
        bad = page_event()
        bad['part']['state']['input']['limit'] = 50
        for event, accepted in [(page_event(), True), (bad, False)]:
            raw = ''.join(json.dumps(e) + '\n' for e in [event, FINISH]).encode()

            def process(*args, stdout, **kwargs):
                stdout.write(raw)
                stdout.flush()
                return Mock(returncode=0, poll=Mock(return_value=0))

            with (
                tempfile.TemporaryDirectory() as temp,
                patch('gui_agent_bench.runners.opencode.subprocess.Popen', side_effect=process),
                patch('gui_agent_bench.runners.opencode.inspect', return_value={'State': {'ExitCode': 0}}),
            ):
                logs = Path(temp)
                if accepted:
                    self.assertEqual(run('test-agent', logs, 30)['diagnostics']['issues'], [])
                else:
                    with self.assertRaises(Failure) as caught:
                        run('test-agent', logs, 30)
                    self.assertEqual(caught.exception.cause, 'evidence_overflow')
                self.assertEqual((logs / 'trajectory.ndjson').read_bytes(), raw)
                self.assertTrue((logs / 'summary.json').is_file())


if __name__ == '__main__':
    unittest.main()
