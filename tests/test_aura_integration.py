"""AURA example: task-local references, shared app build and declared preparation."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

TASK_ID = 'tv/aura-013-caption-preview-size'
TASK = ROOT / 'tasks' / TASK_ID
GENERATED_ARMS = ('oracle_visual', 'oracle_ui', 'test_visual', 'test_ui')


class AuraExampleTests(unittest.TestCase):
    def test_task_local_reference_supports_all_six_arms(self):
        from gui_agent_bench.arms import ARM_IDS
        from gui_agent_bench import reference, task_runtime
        from gui_agent_bench.task_package import verify

        self.assertIn(TASK_ID, task_runtime.TASK_IDS)
        self.assertEqual(reference.control_for(TASK_ID), TASK_ID)
        self.assertEqual(verify(TASK)['status'], 'pass')
        self.assertEqual(task_runtime.runtime(TASK)['environment_profile'], 'generic')
        for arm in ARM_IDS:
            reference.validate(TASK_ID, arm)

    def test_fixture_dispatch_uses_the_task_local_programs(self):
        from gui_agent_bench import oracle_fixtures, test_fixtures, visual_fixtures
        from gui_agent_bench.reference_controls import CONTROLS
        from gui_agent_bench.task_package import load_control
        from gui_agent_bench import reference

        control = reference.control_for(TASK_ID)
        record = load_control(TASK)
        for arm in GENERATED_ARMS:
            dispatcher = test_fixtures if arm.startswith('test_') else oracle_fixtures
            self.assertEqual(dispatcher.source(control, arm), record['programs'][arm])
        self.assertEqual(visual_fixtures.journey(control), record['journey'])
        self.assertEqual(visual_fixtures.regions(control, True), record['regions']['true'])
        self.assertEqual(visual_fixtures.response_delay([], control, 'test_visual'), record['initial_delay'])
        self.assertEqual(
            visual_fixtures.response_delay(
                [{'role': 'assistant', 'tool_calls': [{'function': {'name': 'gui_observe'}}]}], control, 'test_visual'
            ),
            record['action_delay'],
        )
        self.assertIs(CONTROLS[control].record['capture_ui'], True)

    def test_scripted_ui_controls_capture_their_selected_images(self):
        from gui_agent_bench.gateway import fixture_reply
        from gui_agent_bench import reference

        control = reference.control_for(TASK_ID)
        for arm in GENERATED_ARMS:
            with self.subTest(arm=arm):
                messages, observations = [], []
                for _ in range(100):
                    message, reason = fixture_reply(messages, 'PASS', False, arm, control, 'web')
                    if reason == 'stop':
                        break
                    messages.append(message)
                    for call in message['tool_calls']:
                        function = call['function']
                        if function['name'] == 'gui_observe':
                            arguments = json.loads(function['arguments'])
                            if 'reference' in arguments:
                                observations.append(arguments['reference'])
                else:
                    self.fail('Scripted AURA fixture did not terminate')
                self.assertEqual(observations, ['screen', 'saved'] if arm.startswith('test_') else ['saved'])

    def test_build_uses_shared_aura_context_and_keeps_isolation(self):
        from gui_agent_bench import docker as docker_module
        from gui_agent_bench.task_runtime import runtime

        with patch.object(docker_module.subprocess, 'run') as run:
            docker_module.build(ROOT, TASK_ID, app_only=True)
        self.assertEqual(
            run.call_args.args[0],
            [
                'docker',
                'build',
                '--tag',
                runtime(TASK)['app_image'],
                '--file',
                str(ROOT / 'runtime/aura/Dockerfile'),
                str(ROOT),
            ],
        )
        self.assertIn('--read-only', docker_module.isolation())
        self.assertIn('--cap-drop=ALL', docker_module.isolation())

    def test_fixed_clock_and_initial_landmark_are_declared_by_the_task(self):
        from gui_agent_bench.task_runtime import runtime, browser_args

        config = runtime(TASK)
        self.assertEqual(
            config['web_preparation'],
            {
                'ready': [{'role': 'button', 'name': 'Settings'}],
                'fixed_clock': '2026-10-12T18:00:00+00:00',
                'wait_for_fonts': True,
                'reset_timeout_sec': 30,
            },
        )
        args = browser_args(config)
        self.assertEqual(json.loads(args[args.index('--preparation') + 1]), config['web_preparation'])


if __name__ == '__main__':
    unittest.main()
