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
from gui_agent_bench.runners.opencode import configuration


def record(text, matched, precondition=False):
    from test_visual import assertion

    return {'assertion': assertion(reference=text, precondition=precondition), 'matched': matched}


class OracleBoundaries(unittest.TestCase):
    def test_crashes_denials_missing_checks_and_precondition_failures_never_detect_faults(self):
        valid = [record('screen', True, True), record('expected', False)]
        for records, exit_code, failure, expected in [
            (valid, 1, None, 'ERROR'),
            (valid, 0, 'TIMEOUT', 'TIMEOUT'),
            (valid + [{'denied': True}], 0, None, 'INVALID'),
            ([], 0, None, 'INVALID'),
            ([record('x', False)], 0, None, 'INVALID'),
            (list(reversed(valid)), 0, None, 'INVALID'),
            ([record('screen', False, True), record('expected', False)], 0, None, 'SETUP_ERROR'),
        ]:
            self.assertEqual(classify(records, exit_code, failure)['outcome'], expected)

    def test_same_artifact_must_make_same_checks_and_discriminate_both_states(self):
        positive = classify([record('screen', True, True), record('expected', True)], 0)
        negative = classify([record('screen', True, True), record('expected', False)], 0)
        runs = EXECUTIONS_PER_VERSION
        self.assertEqual(pair_result([positive, negative] * runs)['reward'], 1)
        for values in [
            [],
            [positive, negative],
            [positive, positive] * runs,
            [negative, negative] * runs,
            [negative, positive] * runs,
            [positive, negative] * (runs - 1),
        ]:
            self.assertEqual(pair_result(values)['reward'], 0)
        conditional = copy.deepcopy(negative)
        conditional['assertions'][1]['assertion']['reference'] = 'unrelated'
        self.assertEqual(pair_result([positive, conditional] * runs)['reward'], 0)

    def test_every_repetition_must_agree_on_both_versions(self):
        positive = classify([record('screen', True, True), record('expected', True)], 0)
        negative = classify([record('screen', True, True), record('expected', False)], 0)
        unusable = classify([record('screen', False, True), record('expected', True)], 0)
        stable = [positive, negative] * EXECUTIONS_PER_VERSION
        self.assertTrue(pair_result(stable)['stable'])
        for index, replacement in [(0, negative), (1, positive), (8, unusable), (9, unusable)]:
            with self.subTest(index=index):
                flaky = list(stable)
                flaky[index] = replacement
                result = pair_result(flaky)
                self.assertEqual(result['reward'], 0)
        flaky = list(stable)
        flaky[2] = negative
        result = pair_result(flaky)
        self.assertEqual(result['status'], 'graded')
        self.assertFalse(result['stable'])
        self.assertEqual(result['diagnostics']['issues'][-1]['cause'], 'unstable_execution')
        self.assertEqual(pair_result(stable, ['faulty', 'correct'] * EXECUTIONS_PER_VERSION)['reward'], 0)

    def test_visual_execution_rejects_ui_queries_and_malformed_pixel_regions(self):
        query = {
            'kind': 'ui',
            'query': {'text': 'secret'},
            'condition': 'visible',
            'expected': True,
            'precondition': False,
        }
        with self.assertRaises(ValueError):
            validate_assertion(query, 'oracle_visual', (960, 640))
        for region in [[0, 0, 961, 100], [True, 0, 20, 30], [-1, 0, 20, 30], 'selector']:
            args = record('screen', True)['assertion'] | {'region': region}
            with self.assertRaises(ValueError):
                validate_assertion(args, 'oracle_visual', (960, 640))

    def test_visual_authoring_has_no_ui_tools_or_selector_actions(self):
        self.assertNotIn('dump_ui', {tool['name'] for tool in tools_for('oracle_visual')})
        for action in [
            {'action': 'click', 'role': 'button', 'name': 'x'},
            {'action': 'click', 'x': 960, 'y': 0},
            {'action': 'evaluate', 'code': '1'},
        ]:
            with self.assertRaises(ValueError):
                validate_visual_step(action, (960, 640))
        validate_visual_step({'action': 'click', 'x': 12, 'y': 24}, (960, 640))

    def test_oracle_workspaces_exclude_test_source_screenshots_and_private_data(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'steps.json').write_text('["Open", "Act", "Inspect"]')
            for arm in ('oracle_visual', 'oracle_ui'):
                manifest = materialize(ROOT, ROOT / 'tasks/web/webarena-399-profile-bio', folder, folder / arm, arm)
                self.assertEqual(set(manifest['files']), {'instruction.md', 'steps.json'})
                config = configuration(ROOT, folder / (arm + '.json'), 'relay', 'scripted', arm)
                self.assertEqual(config['permission'].get('gui_dump_ui') == 'allow', arm == 'oracle_ui')

    def test_sealing_never_executes_top_level_code(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            code = folder / 'source.py'
            code.write_text('raise RuntimeError("must not execute")\ndef check(page): pass\n')
            sha = seal(code, folder / 'sealed/oracle.py')
            self.assertEqual(len(sha), 64)
            self.assertEqual(code.read_bytes(), (folder / 'sealed/oracle.py').read_bytes())
            code.write_text('x' * 65537)
            with self.assertRaises(ValueError):
                seal(code, folder / 'sealed/other.py')


class RepeatedExecution(unittest.TestCase):
    def verify(self, arm, deadline=None):
        from unittest.mock import patch
        from gui_agent_bench.verifier import oracle

        positive = classify([record('screen', True, True), record('expected', True)], 0)
        negative = classify([record('screen', True, True), record('expected', False)], 0)
        calls = []

        def execute(task, artifact, folder, variant, arm, sha, timeout, references, references_sha):
            calls.append((variant, timeout))
            return copy.deepcopy(positive if variant == 'correct' else negative)

        with tempfile.TemporaryDirectory() as temp:
            artifact = Path(temp) / 'program.py'
            artifact.write_text(
                'def test(page):\n    pass\n' if arm.startswith('test_') else 'def check(page):\n    pass\n'
            )
            with (
                patch.object(oracle, 'execute', side_effect=execute),
                patch.object(oracle, 'seal_references', return_value='refs'),
            ):
                result = oracle.verify_pair(
                    ROOT / 'tasks/web/webarena-399-profile-bio',
                    artifact,
                    Path(temp) / 'out',
                    arm,
                    references=Path(temp),
                    deadline=deadline,
                )
        return result, calls

    def test_each_version_runs_five_times_interleaved_with_its_time_limit(self):
        for arm, limit in (('oracle_ui', 60), ('test_ui', 360)):
            with self.subTest(arm=arm):
                result, calls = self.verify(arm)
                self.assertEqual(result['reward'], 1)
                self.assertEqual(result['planned_executions'], 2 * EXECUTIONS_PER_VERSION)
                self.assertEqual([v for v, _ in calls], ['correct', 'faulty'] * EXECUTIONS_PER_VERSION)
                self.assertEqual({t for _, t in calls}, {limit})

    def test_paired_attempt_deadline_bounds_every_execution(self):
        import time

        result, calls = self.verify('test_ui', deadline=time.monotonic() + 30)
        self.assertEqual(len(calls), 2 * EXECUTIONS_PER_VERSION)
        self.assertTrue(all(1 <= t <= 30 for _, t in calls))


if __name__ == '__main__':
    unittest.main()
