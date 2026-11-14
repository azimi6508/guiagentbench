"""No trial execution or raw command/credential output from prerequisite checks."""

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from gui_agent_bench.preflight import check, mobile_ready
from gui_agent_bench.run_plan import prepare


class PreflightTests(unittest.TestCase):
    def setUp(self):
        qualification = patch('gui_agent_bench.fairness.require')
        qualification.start()
        self.addCleanup(qualification.stop)

    def plan(self, model='fixture/scripted'):
        return prepare(
            ROOT,
            {
                'schema': 'run-plan-v1',
                'models': [model],
                'tasks': [{'task': 'web/webarena-399-profile-bio', 'arms': ['judge_visual']}],
            },
        )

    def test_unavailable_docker_skips_image_probes_and_never_logs_raw_exception(self):
        with patch('gui_agent_bench.preflight.command', side_effect=RuntimeError('secret-token')) as command:
            report = check(ROOT, self.plan())
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(command.call_count, 1)
        self.assertNotIn('secret-token', json.dumps(report))
        self.assertEqual(report['diagnostics']['issues'][0]['cause'], 'infrastructure_error')

    def test_wrong_engine_and_missing_image_are_preflight_failures(self):
        with patch('gui_agent_bench.preflight.command', return_value='windows'):
            self.assertEqual(check(ROOT, self.plan())['status'], 'failed')

        def command(*args, **kwargs):
            if args[1] == 'info':
                return 'linux'
            raise RuntimeError('missing')

        with patch('gui_agent_bench.preflight.command', side_effect=command):
            report = check(ROOT, self.plan())
        self.assertTrue(any(c['name'] == 'docker_image' and c['status'] == 'failed' for c in report['checks']))

    def test_ready_web_judge_requires_only_selected_runtime_images(self):
        with patch('gui_agent_bench.preflight.command', return_value='linux') as command:
            report = check(ROOT, self.plan())
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(command.call_count, 4)  # engine + agent, worker, smoke app
        self.assertFalse(any('oracle' in str(c) for c in command.call_args_list))

    def test_local_image_inspection_uses_canonical_names_when_short_tags_fail(self):
        inspected = []

        def command(*args, **kwargs):
            if args[1] == 'info':
                return 'linux'
            self.assertEqual(args[1:3], ('image', 'inspect'))
            inspected.append(args[3])
            if not args[3].startswith('docker.io/library/'):
                raise RuntimeError('No such image')
            return 'sha256:' + 'a' * 64

        with patch('gui_agent_bench.preflight.command', side_effect=command):
            report = check(ROOT, self.plan())
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(
            set(inspected),
            {
                'docker.io/library/gui-agent-bench-public-agent:1',
                'docker.io/library/gui-agent-bench-public-worker:1',
                'docker.io/library/gui-agent-bench-public-webarena:399',
            },
        )

    def test_missing_scripted_solution_is_reported_once_per_task_arm_not_repeat(self):
        plan = prepare(
            ROOT,
            {
                'schema': 'run-plan-v1',
                'models': ['fixture/scripted'],
                'tasks': [
                    {
                        'task': 'web/webarena-399-profile-bio',
                        'arms': ['test_visual'],
                        'repeats': 3,
                        'fixture_program': 'profile-bio',
                    }
                ],
            },
        )
        with (
            patch('gui_agent_bench.preflight.command', return_value='linux'),
            patch('gui_agent_bench.test_fixtures.source', side_effect=ValueError('Unauthored control')),
        ):
            report = check(ROOT, plan)
        errors = [c for c in report['checks'] if c['name'] == 'scripted_control' and c['status'] == 'failed']
        self.assertEqual(len(errors), 1)

    def test_credentials_checked_only_for_selected_provider_and_never_serialized(self):
        with patch('gui_agent_bench.preflight.command', return_value='linux'), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(check(ROOT, self.plan())['status'], 'passed')
            self.assertEqual(check(ROOT, self.plan('openrouter/example'))['status'], 'failed')
        with (
            patch('gui_agent_bench.preflight.command', return_value='linux'),
            patch.dict(os.environ, {'OPENROUTER_API_KEY': 'never-log-me'}),
        ):
            report = check(ROOT, self.plan('openrouter/example'))
        self.assertEqual(report['status'], 'passed')
        self.assertNotIn('never-log-me', json.dumps(report))

    def test_native_identity_is_checked_before_runtime_reads(self):
        with (
            patch('gui_agent_bench.mobile_driver.safe_device', side_effect=RuntimeError()),
            patch('gui_agent_bench.mobile_runtime.verify_runtime') as verify,
        ):
            with self.assertRaises(RuntimeError):
                mobile_ready(ROOT)
            verify.assert_not_called()

    def test_selected_native_prerequisites_are_reported_without_launching(self):
        spec = {
            'schema': 'run-plan-v1',
            'models': ['fixture/scripted'],
            'tasks': [
                {'task': 'mobile/markor-note-persistence', 'arms': ['judge_visual'], 'fixture_program': 'markor'}
            ],
        }
        with (
            patch('gui_agent_bench.preflight.command', return_value='linux'),
            patch('gui_agent_bench.preflight.verify_task'),
            patch('gui_agent_bench.preflight.check_mobile', side_effect=RuntimeError()) as native,
        ):
            report = check(ROOT, prepare(ROOT, spec))
        native.assert_called_once_with(ROOT)
        errors = {c['name'] for c in report['checks'] if c['status'] == 'failed'}
        self.assertEqual(errors, {'native_runtime'})

    def test_preflight_cli_has_nonzero_exit_without_creating_a_run(self):
        from gui_agent_bench.run_plan import main

        with (
            patch('gui_agent_bench.preflight.check', return_value={'status': 'failed', 'checks': []}),
            patch('gui_agent_bench.run_plan.execute') as execute,
        ):
            code = main(
                ['run', '--plan', str(ROOT / 'jobs/examples-scripted.json'), '--allow-candidate', '--preflight-only'],
                ROOT,
            )
        self.assertEqual(code, 1)
        execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
