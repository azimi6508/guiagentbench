"""Viewer behavior on imperfect evidence and across runners."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from gui_agent_bench.viewer.evidence import EvidenceIndex, json_file
from gui_agent_bench.viewer.review import classify, short_reason, total_tokens


class ViewerRobustnessTests(unittest.TestCase):
    def test_non_finite_numbers_make_a_record_unreadable_not_the_response(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'judgment.json').write_text('{"verdict": "PASS", "confidence": NaN}')
            (Path(folder) / 'summary.json').write_text('{"status": "complete"}')
            self.assertEqual(json_file(Path(folder), 'judgment.json'), ({}, 'Unreadable, incomplete or invalid record'))
            self.assertEqual(json_file(Path(folder), 'summary.json'), ({'status': 'complete'}, None))

    def test_viewer_root_may_sit_below_a_symlinked_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            real = Path(folder) / 'real/runs'
            real.mkdir(parents=True)
            os.symlink(Path(folder) / 'real', Path(folder) / 'alias')
            index = EvidenceIndex(Path(folder) / 'alias/runs')
            self.assertEqual(index.root, real.resolve())

    def test_token_totals_cover_runners_without_a_recorded_total(self):
        self.assertEqual(total_tokens({'inputTokens': 100, 'outputTokens': 5, 'totalTokens': 105}), 105)
        self.assertEqual(
            total_tokens(
                {'inputTokens': 8, 'outputTokens': 1020, 'cacheCreationInputTokens': 533, 'cacheReadInputTokens': 85750}
            ),
            87311,
        )
        self.assertIsNone(total_tokens({}))

    def test_missing_summary_of_a_finished_attempt_needs_review(self):
        row = {'status': 'incomplete'}
        self.assertEqual(classify(row), 'running')
        self.assertEqual(classify(row, 'running'), 'running')
        self.assertEqual(classify(row, 'complete'), 'error')
        self.assertEqual(classify({'status': 'running'}, 'complete'), 'running')

    def test_default_reasons_do_not_claim_zero_credit_for_unresolved_results(self):
        plan = {'arm': 'judge_visual'}
        self.assertEqual(short_reason(plan, [], 'unpaired'), 'Single-state judgment')
        self.assertEqual(short_reason(plan, [], 'unresolved'), 'Result not recorded')
        self.assertEqual(short_reason(plan, [], 'zero'), 'Zero credit')


if __name__ == '__main__':
    unittest.main()
