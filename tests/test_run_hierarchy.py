"""Fixed run membership, honest aggregates and portable historical evidence."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from gui_agent_bench.run_plan import execute, prepare
from gui_agent_bench.viewer.evidence import EvidenceIndex


class HierarchyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value), encoding='utf-8')

    def evaluation(self, path, task='web/example', arm='test_ui', score=1, status='complete', model='fixture/scripted'):
        self.put(
            path + '/plan.json',
            {
                'task': task,
                'arm': arm,
                'model': model,
                'fixture': model == 'fixture/scripted',
                'planned_trials': 1,
                'trials': [{'id': 'one', 'variant': 'correct'}],
            },
        )
        self.put(path + '/summary.json', {'status': status, 'paired_score': score, 'completed_trials': 1})

    def hierarchy(self):
        return EvidenceIndex(self.root).hierarchy()

    def test_native_missing_plan_cells_stay_in_denominator_and_retries_do_not_replace_failure(self):
        self.evaluation('group/evaluations/failed', score=0)
        self.evaluation('group/evaluations/later', score=1)
        self.put(
            'group/run.json',
            {
                'schema': 'run-v1',
                'name': 'Two domains',
                'cells': [
                    {
                        'task': 'web/example',
                        'arm': 'test_ui',
                        'model': 'fixture/scripted',
                        'attempts': [{'path': 'evaluations/failed'}, {'path': 'evaluations/later'}],
                    },
                    {'task': 'mobile/example', 'arm': 'judge_visual', 'model': 'fixture/scripted', 'attempts': []},
                ],
            },
        )
        h = self.hierarchy()
        self.assertEqual(len(h['runs']), 1)
        r = h['runs'][0]
        self.assertEqual(r['platforms'], ['mobile', 'web'])
        self.assertEqual(
            r['totals'], {'planned': 2, 'finished': 1, 'credited': 0, 'zero': 1, 'missing': 1, 'attempts': 2}
        )
        self.assertEqual(len(r['tasks'][0]['cells'][0]['attempts']), 2)

    def test_historical_checkout_relocation_uses_full_runs_relative_path(self):
        self.evaluation('abc')
        self.put(
            'campaign/plan.json', {'tasks': [{'task': 'web/example'}], 'arms': ['test_ui'], 'planned_task_arm_pairs': 1}
        )
        self.put(
            'campaign/report.json',
            {
                'cells': [
                    {
                        'task': 'web/example',
                        'arm': 'test_ui',
                        'attempts': [{'run_directory': 'C:\\old\\checkout\\runs\\abc'}],
                    }
                ]
            },
        )
        h = self.hierarchy()
        self.assertEqual(len(h['runs']), 1)
        self.assertEqual(h['runs'][0]['totals']['credited'], 1)

    def test_tv_reference_resolves_nested_runs_segment_and_preserves_missing_arm(self):
        self.evaluation('tv-campaign/runs/a', task='tv/example', arm='test_visual')
        self.put(
            'tv-campaign/plan.json',
            {
                'planned_task_arm_pairs': 2,
                'cells': [{'task': 'tv/example', 'arm': 'test_visual'}, {'task': 'tv/example', 'arm': 'judge_visual'}],
            },
        )
        self.put(
            'tv-campaign/report.json',
            {'cells': [{'task': 'tv/example', 'arm': 'test_visual', 'run': 'runs/tv-campaign/runs/a'}]},
        )
        r = self.hierarchy()['runs'][0]
        self.assertEqual(r['totals']['planned'], 2)
        self.assertEqual(r['totals']['credited'], 1)
        direct = EvidenceIndex(self.root / 'tv-campaign').hierarchy()
        self.assertEqual(len(direct['runs']), 1)
        self.assertEqual(direct['runs'][0]['totals']['credited'], 1)

    def test_reference_cannot_escape_index_or_attach_wrong_task_model(self):
        self.evaluation('other')
        for ref in ('../other', 'C:/outside/other', '/other', 'other'):
            self.put(
                'run.json',
                {'schema': 'run-v1', 'cells': [{'task': 'web/wrong', 'arm': 'test_ui', 'attempts': [{'path': ref}]}]},
            )
            h = self.hierarchy()
            self.assertEqual(len(h['runs']), 2)
            grouped = next(r for r in h['runs'] if r['kind'] == 'run')
            self.assertEqual(grouped['totals']['credited'], 0)

    def test_provisional_reward_not_final_credit_and_single_state_not_pair(self):
        self.evaluation('running', score=1, status='running')
        self.evaluation('single', arm='judge_visual')
        self.put('single/summary.json', {'status': 'complete', 'planned_pairs': 0, 'paired_score': None})
        self.assertTrue(all(r['totals']['credited'] == 0 for r in self.hierarchy()['runs']))

    def test_duplicate_reference_and_malformed_manifest_leave_individuals_visible(self):
        self.evaluation('group/a')
        self.put(
            'group/run.json',
            {
                'schema': 'run-v1',
                'cells': [{'task': 'web/example', 'arm': 'test_ui', 'attempts': [{'path': 'a'}, {'path': 'a'}]}],
            },
        )
        h = self.hierarchy()
        self.assertEqual(len(h['warnings']), 1)
        self.assertEqual(h['runs'][0]['kind'], 'single')
        self.put('group/run.json', {'schema': 'run-v1', 'cells': [None]})
        self.assertEqual(len(self.hierarchy()['warnings']), 1)

    def test_native_direct_root_live_container_reference_and_new_record(self):
        self.put(
            'run.json',
            {
                'schema': 'run-v1',
                'cells': [
                    {
                        'task': 'web/example',
                        'arm': 'test_ui',
                        'attempts': [{'path': 'evaluations/0000/attempt-1', 'status': 'running'}],
                    }
                ],
            },
        )
        index = EvidenceIndex(self.root)
        self.assertEqual(index.hierarchy()['runs'][0]['totals']['missing'], 1)
        self.evaluation('evaluations/0000/attempt-1/opaque', status='running')
        index.refresh(force=True)
        r = index.hierarchy()['runs'][0]
        self.assertEqual(r['totals']['missing'], 0)
        self.assertEqual(r['totals']['finished'], 0)

    def test_historical_complete_label_with_invalid_results_is_displayed_as_errors(self):
        self.evaluation('group/a', score=0)
        self.put(
            'group/run.json',
            {
                'schema': 'run-v1',
                'status': 'complete',
                'cells': [
                    {
                        'task': 'web/example',
                        'arm': 'test_ui',
                        'attempts': [{'path': 'a', 'status': 'complete', 'invalid_or_missing': 1}],
                    }
                ],
            },
        )
        source = (self.root / 'group/run.json').read_bytes()
        run = self.hierarchy()['runs'][0]
        self.assertEqual(run['status'], 'completed_with_errors')
        self.assertEqual(run['recorded_status'], 'complete')
        self.assertEqual(run['tasks'][0]['cells'][0]['attempts'][0]['status'], 'failed')
        self.assertEqual(source, (self.root / 'group/run.json').read_bytes())

    def test_model_caused_invalid_result_is_zero_credit_even_in_historical_failed_records(self):
        self.evaluation('group/a', score=0, model='openrouter/example')
        self.put('group/a/summary.json', {'status': 'complete', 'paired_score': 0, 'invalid_or_missing': 1})
        self.put(
            'group/a/trials/one/logs/verifier/metrics.json',
            {
                'diagnostics': {
                    'issues': [
                        {
                            'version': 'failure-v1',
                            'phase': 'sealing',
                            'cause': 'missing_submission',
                            'impact': 'zero_credit',
                        }
                    ]
                }
            },
        )
        self.put(
            'group/run.json',
            {
                'schema': 'run-v1',
                'status': 'completed_with_errors',
                'cells': [
                    {
                        'task': 'web/example',
                        'arm': 'test_ui',
                        'model': 'openrouter/example',
                        'attempts': [{'path': 'a', 'status': 'failed', 'invalid_or_missing': 1}],
                    }
                ],
            },
        )
        run = self.hierarchy()['runs'][0]
        attempt = run['tasks'][0]['cells'][0]['attempts'][0]
        self.assertTrue(attempt['record']['model_zero'])
        self.assertEqual((attempt['status'], attempt['recorded_status']), ('complete', 'failed'))
        self.assertEqual(run['status'], 'completed_with_errors')
        self.put(
            'group/a/plan.json',
            {
                'task': 'web/example',
                'arm': 'test_ui',
                'model': 'fixture/scripted',
                'fixture': True,
                'trials': [{'id': 'one', 'variant': 'correct'}],
            },
        )
        self.put(
            'group/run.json',
            {
                'schema': 'run-v1',
                'cells': [
                    {
                        'task': 'web/example',
                        'arm': 'test_ui',
                        'model': 'fixture/scripted',
                        'attempts': [{'path': 'a', 'status': 'failed', 'invalid_or_missing': 1}],
                    }
                ],
            },
        )
        attempt = self.hierarchy()['runs'][0]['tasks'][0]['cells'][0]['attempts'][0]
        self.assertFalse(attempt['record']['model_zero'])
        self.assertEqual(attempt['status'], 'failed')

    def test_running_attempt_of_an_ended_run_is_interrupted_and_not_a_separate_run(self):
        self.evaluation('group/evaluations/0000/attempt-1/opaque', status='running')
        self.put(
            'group/run.json',
            {
                'schema': 'run-v1',
                'status': 'interrupted',
                'cells': [
                    {
                        'task': 'web/example',
                        'arm': 'test_ui',
                        'model': 'fixture/scripted',
                        'attempts': [{'path': 'evaluations/0000/attempt-1', 'status': 'running'}],
                    }
                ],
            },
        )
        runs = self.hierarchy()['runs']
        self.assertEqual([r['kind'] for r in runs], ['run'])
        self.assertEqual(runs[0]['tasks'][0]['cells'][0]['attempts'][0]['status'], 'interrupted')
        self.assertEqual(runs[0]['totals']['zero'], 1)
        self.assertEqual(runs[0]['totals']['missing'], 0)

    def test_preflight_report_and_missing_denominator_are_visible(self):
        self.put(
            'group/run.json',
            {
                'schema': 'run-v1',
                'status': 'preflight_failed',
                'preflight': {'status': 'failed', 'checks': [{'status': 'failed', 'message': 'Docker unavailable'}]},
                'cells': [{'task': 'web/example', 'arm': 'test_ui', 'attempts': []}],
            },
        )
        run = self.hierarchy()['runs'][0]
        self.assertEqual(run['status'], 'preflight_failed')
        self.assertEqual(run['totals']['planned'], 1)
        self.assertEqual(run['totals']['attempts'], 0)
        self.assertEqual(run['preflight']['checks'][0]['message'], 'Docker unavailable')


class RunPlanTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch

        qualification = patch('gui_agent_bench.fairness.require')
        qualification.start()
        cohort = patch('gui_agent_bench.fairness.TASKS', ())
        cohort.start()
        self.addCleanup(cohort.stop)
        self.addCleanup(qualification.stop)

    @staticmethod
    def ready(*args):
        return {'status': 'passed', 'checks': [], 'diagnostics': {'version': 'failure-v1', 'issues': []}}

    def spec(self):
        return {
            'schema': 'run-plan-v1',
            'name': 'Test plan',
            'models': ['fixture/scripted'],
            'tasks': [{'task': 'web/webarena-399-profile-bio', 'arms': ['judge_visual', 'test_ui']}],
        }

    def test_plan_validates_entire_matrix_and_candidate_gates(self):
        spec = json.loads((ROOT / 'jobs/examples-scripted.json').read_text())
        self.assertEqual(len(prepare(ROOT, spec)['cells']), 18)
        spec['tasks'] = [{'task': 'web/unknown', 'arms': ['test_ui']}]
        with self.assertRaises(ValueError):
            prepare(ROOT, spec)

    def test_multi_model_repeats_and_duplicate_validation(self):
        spec = self.spec()
        spec['models'].append('openrouter/example')
        spec['tasks'][0]['repeats'] = 2
        self.assertEqual(len(prepare(ROOT, spec)['cells']), 8)
        spec['tasks'].append(spec['tasks'][0])
        with self.assertRaises(ValueError):
            prepare(ROOT, spec)

    def test_controller_failure_continues_with_all_cells_preserved_and_never_retries(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp:

            def runner(root, task, arm, variant, model, destination, *args):
                manifest = json.loads((destination.parents[2] / 'run.json').read_text())
                self.assertEqual(len(manifest['cells']), 2)
                calls.append(arm)
                if len(calls) == 1:
                    raise RuntimeError('Setup failed')
                child = destination / 'opaque'
                child.mkdir()
                return {'run_directory': str(child), 'status': 'complete', 'invalid_or_missing': 0}

            folder, manifest = execute(ROOT, self.spec(), Path(temp), runner=runner, preflight=self.ready)
            self.assertEqual(calls, ['judge_visual', 'test_ui'])
            self.assertEqual(manifest['status'], 'completed_with_errors')
            self.assertEqual(manifest['cells'][0]['attempts'][0]['status'], 'failed')
            self.assertEqual(manifest['cells'][1]['attempts'][0]['status'], 'complete')
            self.assertTrue(all(len(c['attempts']) == 1 for c in manifest['cells']))
            self.assertEqual(manifest['result']['failed'], 1)
            self.assertEqual(manifest['result']['planned'], 2)
            self.assertEqual(manifest['result']['unstarted'], 0)
            self.assertEqual(manifest, json.loads((folder / 'run.json').read_text()))

    def test_interrupt_preserves_remaining_planned_cells(self):
        with tempfile.TemporaryDirectory() as temp:

            def runner(*args):
                raise KeyboardInterrupt()

            with self.assertRaises(KeyboardInterrupt):
                execute(ROOT, self.spec(), Path(temp), runner=runner, preflight=self.ready)
            manifest = json.loads(next(Path(temp).glob('*/run.json')).read_text())
            self.assertEqual(manifest['status'], 'interrupted')
            self.assertEqual(manifest['cells'][1]['attempts'], [])

    def test_preflight_failure_reserves_plan_without_invoking_runner(self):
        from unittest.mock import Mock

        runner = Mock()
        with tempfile.TemporaryDirectory() as temp:
            folder, manifest = execute(
                ROOT,
                self.spec(),
                Path(temp),
                runner=runner,
                preflight=lambda *args: {
                    'status': 'failed',
                    'checks': [{'status': 'failed', 'message': 'Docker unavailable'}],
                },
            )
            runner.assert_not_called()
            self.assertEqual(manifest['status'], 'preflight_failed')
            self.assertEqual(manifest['result']['unstarted'], 2)
            self.assertEqual(json.loads((folder / 'run.json').read_text()), manifest)

    def run_summaries(self, invalid=0, issues=None, model='openrouter/example'):
        calls = []
        spec = self.spec()
        spec['models'] = [model]

        def runner(root, task, arm, variant, model, destination, *args):
            calls.append(arm)
            child = destination / 'opaque'
            metrics = child / 'trials/one/logs/verifier/metrics.json'
            metrics.parent.mkdir(parents=True)
            metrics.write_text(json.dumps({'diagnostics': {'issues': issues or []}}))
            return {
                'run_directory': str(child),
                'status': 'complete',
                'paired_score': 0,
                'planned_pairs': 1,
                'invalid_or_missing': invalid,
            }

        with tempfile.TemporaryDirectory() as temp:
            _, manifest = execute(ROOT, spec, Path(temp), runner=runner, preflight=self.ready)
        return calls, manifest

    def test_valid_zero_reward_is_completed_and_does_not_stop(self):
        calls, manifest = self.run_summaries()
        self.assertEqual(len(calls), 2)
        self.assertEqual(manifest['status'], 'complete')
        self.assertEqual(manifest['result']['failed'], 0)

    def test_model_caused_invalid_result_is_zero_credit_not_an_error(self):
        calls, manifest = self.run_summaries(
            invalid=1,
            issues=[
                {'version': 'failure-v1', 'phase': 'sealing', 'cause': 'missing_submission', 'impact': 'zero_credit'}
            ],
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(manifest['status'], 'complete')
        self.assertEqual(manifest['result']['failed'], 0)
        self.assertEqual(manifest['result']['credited'], 0)
        attempt = manifest['cells'][0]['attempts'][0]
        self.assertEqual((attempt['status'], attempt['invalid_or_missing'], attempt['score']), ('complete', 1, 0))
        self.assertEqual(attempt['note'], 'missing_submission: No submission was produced.')
        self.assertNotIn('error', attempt)
        self.assertEqual(attempt['diagnostics']['issues'][0]['cause'], 'missing_submission')

    def test_invalid_result_from_scripted_control_is_an_error(self):
        _, manifest = self.run_summaries(
            invalid=1,
            model='fixture/scripted',
            issues=[
                {'version': 'failure-v1', 'phase': 'sealing', 'cause': 'missing_submission', 'impact': 'zero_credit'}
            ],
        )
        self.assertEqual(manifest['status'], 'completed_with_errors')
        self.assertEqual(manifest['result']['failed'], 2)
        self.assertEqual(
            manifest['cells'][0]['attempts'][0]['error'], 'missing_submission: No submission was produced.'
        )

    def test_unclassified_cause_beside_model_cause_needs_review(self):
        calls, manifest = self.run_summaries(
            invalid=1,
            issues=[
                {'version': 'failure-v1', 'phase': 'sealing', 'cause': 'missing_submission', 'impact': 'zero_credit'},
                {
                    'version': 'failure-v1',
                    'phase': 'authoring',
                    'cause': 'capability_unavailable',
                    'impact': 'zero_credit',
                },
            ],
        )
        self.assertEqual(manifest['status'], 'completed_with_errors')
        self.assertIn(
            'capability_unavailable: The required tool configuration was unavailable.',
            manifest['cells'][0]['attempts'][0]['error'],
        )

    def test_invalid_result_without_diagnostics_needs_review(self):
        calls, manifest = self.run_summaries(invalid=1)
        self.assertEqual(manifest['status'], 'completed_with_errors')
        self.assertEqual(
            manifest['cells'][0]['attempts'][0]['error'], 'A missing or invalid result has no recorded diagnostic.'
        )

    def test_interrupt_marks_the_running_attempt_interrupted(self):
        with tempfile.TemporaryDirectory() as temp:

            def runner(*args):
                raise KeyboardInterrupt()

            with self.assertRaises(KeyboardInterrupt):
                execute(ROOT, self.spec(), Path(temp), runner=runner, preflight=self.ready)
            manifest = json.loads(next(Path(temp).glob('*/run.json')).read_text())
        attempt = manifest['cells'][0]['attempts'][0]
        self.assertEqual(attempt['status'], 'interrupted')
        self.assertIn('interrupted', attempt['error'])
        self.assertEqual(manifest['result']['interrupted'], 1)
        self.assertEqual(manifest['result']['finished'], 0)

    def test_setup_failure_in_complete_child_summary_continues_next_evaluation(self):
        calls, manifest = self.run_summaries(
            invalid=1,
            issues=[
                {'version': 'failure-v1', 'phase': 'setup', 'cause': 'unknown_operation_error', 'impact': 'zero_credit'}
            ],
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(manifest['status'], 'completed_with_errors')
        self.assertEqual(manifest['result']['unstarted'], 0)
        self.assertEqual(manifest['result']['failed'], 2)
        self.assertEqual(
            manifest['cells'][0]['attempts'][0]['diagnostics']['issues'][0]['cause'], 'unknown_operation_error'
        )
        self.assertEqual(
            manifest['cells'][0]['attempts'][0]['error'],
            'unknown_operation_error: The operation failed for an unclassified reason.',
        )

    def test_recorded_failures_continue_and_report_errors(self):
        for cause in ('provider_transport_error', 'infrastructure_error', 'target_unavailable'):
            with self.subTest(cause=cause):
                calls, manifest = self.run_summaries(
                    invalid=1,
                    issues=[{'version': 'failure-v1', 'phase': 'authoring', 'cause': cause, 'impact': 'zero_credit'}],
                )
                self.assertEqual(len(calls), 2)
                self.assertEqual(manifest['status'], 'completed_with_errors')


if __name__ == '__main__':
    unittest.main()
