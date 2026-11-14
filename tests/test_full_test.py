"""Tests for the goal-only boundary and action/assertion ledger semantics."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from gui_agent_bench.materialize import materialize
from gui_agent_bench.actions import validate_visual_step
from gui_agent_bench.oracle_broker import tools_for, validate_assertion
from gui_agent_bench.budgets import EXECUTIONS_PER_VERSION
from gui_agent_bench.verifier.oracle import classify, pair_result, seal
from gui_agent_bench.test_fixtures import source


def assertion(text, matched, precondition=False):
    from test_visual import assertion as image_assertion

    return {'assertion': image_assertion(reference=text, precondition=precondition), 'matched': matched}


class FullTestBoundaries(unittest.TestCase):
    def test_workspace_does_not_even_read_the_reference_or_steps(self):
        with tempfile.TemporaryDirectory() as temp:
            task = Path(temp) / 'task'
            task.mkdir()
            (task / 'instruction.md').write_text('Persist an item.')
            for arm in ('test_visual', 'test_ui'):
                workspace = Path(temp) / arm
                result = materialize(ROOT, task, Path(temp) / 'absent-evidence', workspace, arm)
                self.assertEqual(set(result['files']), {'instruction.md'})
                self.assertFalse((workspace / 'steps.json').exists())
                self.assertFalse((workspace / 'test_source.py').exists())

    def test_same_assertions_are_insufficient_if_journey_changes_between_states(self):
        action = {'action': {'operation': 'step', 'arguments': {'action': 'click', 'x': 10, 'y': 10}}}
        checks = [assertion('initial', True, True), action, assertion('expected', True)]
        correct = classify(checks, 0, full_test=True)
        faulty_records = copy.deepcopy(checks)
        faulty_records[-1]['matched'] = False
        faulty = classify(faulty_records, 0, full_test=True)
        self.assertEqual(pair_result([correct, faulty] * EXECUTIONS_PER_VERSION)['reward'], 1)
        faulty_records[1]['action']['arguments']['x'] = 20
        changed = classify(faulty_records, 0, full_test=True)
        self.assertEqual(pair_result([correct, changed] * EXECUTIONS_PER_VERSION)['reward'], 0)
        self.assertEqual(classify([checks[0], checks[2]], 0, full_test=True)['outcome'], 'INVALID')

    def test_test_visual_cannot_gain_ui_queries_or_selector_actions(self):
        self.assertNotIn('dump_ui', {t['name'] for t in tools_for('test_visual')})
        with self.assertRaises(ValueError):
            validate_assertion({'kind': 'ui', 'precondition': False}, 'test_visual', (960, 640))
        with self.assertRaises(ValueError):
            validate_visual_step({'action': 'click', 'role': 'button', 'name': 'Add item'}, (960, 640))

    def test_submitted_test_entry_point_is_sealed_without_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            artifact = Path(temp) / 'test.py'
            artifact.write_text('raise RuntimeError("host must not execute")\ndef test(page): pass\n')
            seal(artifact, Path(temp) / 'sealed/test.py', 'test')
            with self.assertRaises(ValueError):
                seal(artifact, Path(temp) / 'sealed/oracle.py', 'check')

    def test_controls_perform_own_journey_and_do_not_embed_labels(self):
        for arm in ('test_visual', 'test_ui'):
            code = source('markor', arm)
            self.assertIn('def test(page):', code)
            self.assertIn('page.reload()', code)
            self.assertNotIn('variant', code)
            self.assertNotIn('/private', code)


if __name__ == '__main__':
    unittest.main()
