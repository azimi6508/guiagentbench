import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from gui_agent_bench import reference
from gui_agent_bench.arms import generated
from gui_agent_bench.run_plan import prepare


class ReferenceTests(unittest.TestCase):
    def test_every_reference_plan_cell_has_a_handwritten_solution(self):
        for repeats in (1, 3):
            plan = prepare(
                ROOT,
                dict(
                    json.loads((ROOT / 'jobs/examples-reference.json').read_text()),
                    tasks=[
                        dict(t, repeats=repeats)
                        for t in json.loads((ROOT / 'jobs/examples-reference.json').read_text())['tasks']
                    ],
                ),
                True,
            )
            self.assertEqual(len(plan['cells']), 18 * repeats)
            self.assertTrue(plan['reference'])
            for c in plan['cells']:
                reference.validate(c['task'], c['arm'])
                if generated(c['arm']):
                    code = reference.source_for(c['task'], c['arm'])
                    ast.parse(code)
                    self.assertNotIn('/private', code)
                    self.assertNotIn('labels.json', code)
                    self.assertNotIn('settings.json', code)

    def test_reference_judges_bypass_agent_app_and_provider_and_earn_credit(self):
        from gui_agent_bench.reference_audit import audit_reference

        for arm in ('judge_visual', 'judge_test'):
            with (
                tempfile.TemporaryDirectory() as temp,
                patch('gui_agent_bench.docker.docker') as docker,
                patch('gui_agent_bench.runners.opencode_adapter.author') as agent,
            ):
                result = reference.run(ROOT, ROOT / 'tasks/web/webarena-399-profile-bio', arm, 'pair', Path(temp))
                self.assertEqual(result['accuracy'], 1)
                self.assertEqual(result['paired_score'], 1)
                self.assertEqual(result['provider_cost_usd'], 0)
                self.assertFalse(result['research_core'])
                folder = Path(result['run_directory'])
                report = audit_reference(folder)
                self.assertFalse(report['agent_boundary_verified'])
                self.assertTrue(report['agent_bypassed'])
                self.assertFalse(report['runtime_verified'])
                with self.assertRaises(ValueError):
                    audit_reference(folder, require_probes=True)
                docker.assert_not_called()
                agent.assert_not_called()
                self.assertFalse(list(folder.rglob('trajectory.ndjson')))
                plan = json.loads((folder / 'plan.json').read_text())
                for cell in plan['trials']:
                    marker = folder / 'trials' / cell['id'] / 'reference.json'
                    data = json.loads(marker.read_text())
                    self.assertFalse(data['agent_started'])
                    self.assertFalse(data['provider_started'])

    def test_reference_plan_cannot_be_mixed_into_model_scores(self):
        p = {
            'schema': 'run-plan-v1',
            'models': ['reference/solution', 'openrouter/example'],
            'tasks': [{'task': 'web/webarena-399-profile-bio', 'arms': ['judge_visual']}],
        }
        with self.assertRaises(ValueError):
            prepare(ROOT, p)
        p['models'] = ['reference/solution']
        with tempfile.TemporaryDirectory() as temp:
            from gui_agent_bench.run_plan import execute

            with self.assertRaises(ValueError):
                execute(ROOT, p, Path(temp), fixture_probe=True)

    def test_reference_audit_rejects_changed_identity_variants_and_artifact(self):
        from gui_agent_bench.reference_audit import audit_reference

        with tempfile.TemporaryDirectory() as temp:
            result = reference.run(ROOT, ROOT / 'tasks/web/webarena-399-profile-bio', 'judge_test', 'pair', Path(temp))
            folder = Path(result['run_directory'])
            plan_file = folder / 'plan.json'
            original_plan = plan_file.read_text()
            plan = json.loads(original_plan)
            trial = folder / 'trials' / plan['trials'][0]['id']
            marker_file = trial / 'reference.json'
            original_marker = marker_file.read_text()
            marker = json.loads(original_marker)
            marker_file.write_text(json.dumps({**marker, 'scope': 'Model evaluation'}))
            with self.assertRaises(ValueError):
                audit_reference(folder)
            marker_file.write_text(original_marker)
            plan['trials'][1]['variant'] = 'correct'
            plan_file.write_text(json.dumps(plan))
            with self.assertRaises(ValueError):
                audit_reference(folder)
            plan_file.write_text(original_plan)
            artifact = trial / 'output/judgment.json'
            artifact.write_text('{"verdict":"FAIL"}')
            with self.assertRaises(ValueError):
                audit_reference(folder)

    def test_incomplete_reference_credit_fails_validation_without_fabricated_causes(self):
        from gui_agent_bench.run_plan import health, reference_validation_failed

        good = {
            'model': reference.MODEL,
            'reference': True,
            'status': 'complete',
            'accuracy': 1,
            'paired_score': 1,
            'planned_pairs': 1,
            'invalid_or_missing': 0,
        }
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(health(Path(temp), good)['errors'])
            for key, value in (('accuracy', 0.5), ('paired_score', 0), ('invalid_or_missing', 1)):
                bad = {**good, key: value}
                state = health(Path(temp), bad)
                self.assertTrue(state['errors'])
                self.assertEqual(state['diagnostics']['issues'], [])
            self.assertFalse(reference_validation_failed({**good, 'planned_pairs': 0, 'paired_score': None}))
            self.assertFalse(
                reference_validation_failed(
                    {**good, 'reference': False, 'model': 'fixture/scripted', 'accuracy': 0.5, 'paired_score': 0}
                )
            )

    def test_failed_reference_validation_preserves_plan_and_never_retries(self):
        from gui_agent_bench.run_plan import execute

        spec = {
            'schema': 'run-plan-v1',
            'models': [reference.MODEL],
            'tasks': [{'task': 'web/webarena-399-profile-bio', 'arms': ['judge_visual', 'judge_test']}],
        }
        calls = []

        def runner(root, task, arm, variant, model, destination, *args):
            calls.append(arm)
            child = destination / 'opaque'
            child.mkdir()
            return {
                'run_directory': str(child),
                'model': model,
                'reference': True,
                'status': 'complete',
                'accuracy': 0.5 if len(calls) == 1 else 1,
                'paired_score': 0 if len(calls) == 1 else 1,
                'planned_pairs': 1,
                'invalid_or_missing': 0,
            }

        with tempfile.TemporaryDirectory() as temp:
            _, manifest = execute(
                ROOT, spec, Path(temp), runner=runner, preflight=lambda *args: {'status': 'passed', 'checks': []}
            )
        self.assertEqual(calls, ['judge_visual', 'judge_test'])
        self.assertEqual(manifest['status'], 'completed_with_errors')
        self.assertEqual(manifest['result']['planned'], 2)
        self.assertEqual(manifest['result']['failed'], 1)
        self.assertTrue(all(len(c['attempts']) == 1 for c in manifest['cells']))

    def test_cli_reports_zero_reference_credit_but_not_normal_wrong_answers_as_failure(self):
        from gui_agent_bench.cli import main

        base = {'status': 'complete', 'accuracy': 0, 'paired_score': 0, 'planned_pairs': 1, 'invalid_or_missing': 0}
        for model, expected in ((reference.MODEL, 1), ('fixture/scripted', 0)):
            with (
                patch('gui_agent_bench.trial.run', return_value={**base, 'model': model}),
                patch('gui_agent_bench.preflight.require_runtime'),
            ):
                self.assertEqual(main(['run', '--task', 'web/webarena-399-profile-bio', '--model', model]), expected)

    def test_normal_reference_dispatch_does_not_call_evaluated_trial(self):
        from gui_agent_bench.trial import run

        with (
            patch('gui_agent_bench.reference.run', return_value={'reference': True}) as direct,
            patch('gui_agent_bench.trial.run_trial') as evaluated,
        ):
            result = run(
                ROOT,
                'web/webarena-399-profile-bio',
                'judge_visual',
                'pair',
                'reference/solution',
                ROOT / 'runs',
                60,
                'PASS',
                False,
            )
        self.assertTrue(result['reference'])
        direct.assert_called_once()
        evaluated.assert_not_called()
        with self.assertRaises(ValueError):
            run(
                ROOT,
                'web/webarena-399-profile-bio',
                'judge_visual',
                'pair',
                'reference/solution',
                ROOT / 'runs',
                60,
                'PASS',
                True,
            )

    def test_direct_ui_artifact_uses_the_actual_pair_reward(self):
        from gui_agent_bench.visual import reference_digest

        for reward in (0, 1):
            with tempfile.TemporaryDirectory() as temp:
                folder = Path(temp) / 'trial'

                def verify(task, artifact, output, arm, **kwargs):
                    self.assertIn('def check(page)', artifact.read_text())
                    self.assertEqual(artifact.read_bytes(), (folder / 'output/oracle.py').read_bytes())
                    reference_digest(kwargs['references'])
                    return {'status': 'graded', 'reward': reward, 'executions': [], 'planned_trials': 1}

                with (
                    patch('gui_agent_bench.verifier.oracle.verify_pair', side_effect=verify) as paired,
                    patch('gui_agent_bench.reference.prepare_references') as images,
                ):
                    result = reference.run_trial(
                        ROOT, ROOT / 'tasks/web/webarena-399-profile-bio', folder, 'correct', 'oracle_ui'
                    )
                self.assertEqual(result['reward'], reward)
                paired.assert_called_once()
                images.assert_not_called()

    def test_reference_image_preparation_failure_cannot_earn_reward(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch('gui_agent_bench.reference.prepare_references', side_effect=RuntimeError('not ready')),
            patch('gui_agent_bench.verifier.oracle.verify_pair') as paired,
        ):
            r = reference.run_trial(
                ROOT, ROOT / 'tasks/web/webarena-399-profile-bio', Path(temp) / 'trial', 'correct', 'test_visual'
            )
        self.assertEqual(r['reward'], 0)
        self.assertEqual(r['status'], 'trial_error')
        paired.assert_not_called()

    def test_reference_judge_needs_no_docker_native_device_or_tv_assets(self):
        from gui_agent_bench.preflight import check

        plan = prepare(
            ROOT,
            {
                'schema': 'run-plan-v1',
                'models': ['reference/solution'],
                'tasks': [
                    {'task': 'mobile/markor-note-persistence', 'arms': ['judge_visual']},
                    {'task': 'tv/aura-013-caption-preview-size', 'arms': ['judge_test']},
                ],
            },
            True,
        )
        with (
            patch('gui_agent_bench.preflight.command') as command,
            patch('gui_agent_bench.preflight.check_mobile') as mobile,
            patch('gui_agent_bench.tv_session.app_mounts') as tv,
        ):
            result = check(ROOT, plan)
        self.assertEqual(result['status'], 'passed')
        command.assert_not_called()
        mobile.assert_not_called()
        tv.assert_not_called()

    def test_reference_generated_preflight_does_not_require_opencode_image(self):
        from gui_agent_bench.preflight import check

        plan = prepare(
            ROOT,
            {
                'schema': 'run-plan-v1',
                'models': ['reference/solution'],
                'tasks': [{'task': 'web/webarena-399-profile-bio', 'arms': ['test_visual']}],
            },
        )
        with patch('gui_agent_bench.preflight.command', return_value='linux') as command:
            result = check(ROOT, plan)
        self.assertEqual(result['status'], 'passed')
        self.assertFalse(any('gui-agent-bench-public-agent' in str(c) for c in command.call_args_list))
        self.assertTrue(any('gui-agent-bench-public-oracle:' in str(c) for c in command.call_args_list))

    def test_invalid_reference_variant_or_unavailable_tv_arm_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                reference.run(ROOT, ROOT / 'tasks/web/webarena-399-profile-bio', 'judge_test', 'unknown', Path(temp))
            with self.assertRaises(ValueError):
                reference.run(ROOT, ROOT / 'tasks/web/webarena-399-profile-bio', 'test_ui', 'correct', Path(temp))
        with self.assertRaises(ValueError):
            reference.validate('tv/picture-navigation', 'test_ui')
        with self.assertRaises(ValueError):
            reference.validate('web/unknown', 'test_visual')


if __name__ == '__main__':
    unittest.main()
