"""Domain grouping is independent of execution backend and tool capabilities."""

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gui_agent_bench.arms import ARM_IDS
from gui_agent_bench import reference
from gui_agent_bench.task_package import discover, metadata, verify
from gui_agent_bench.task_runtime import runtime
from gui_agent_bench.run_plan import prepare

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = 'tv/aura-013-caption-preview-size'
TASK = ROOT / 'tasks' / TASK_ID


class TaskDomain(unittest.TestCase):
    def test_aura_is_tv_domain_with_all_browser_arms(self):
        self.assertIn(TASK_ID, discover(ROOT))
        self.assertNotIn('web/aura-013-caption-preview-size', discover(ROOT))
        values = runtime(TASK)
        self.assertEqual((values['domain'], values['platform']), ('tv', 'web'))
        self.assertEqual(metadata(TASK)['metadata']['eligible_arms'], list(ARM_IDS))
        self.assertEqual(verify(TASK)['task'], TASK_ID)
        self.assertEqual(reference.control_for(TASK_ID), TASK_ID)
        for arm in ARM_IDS:
            reference.validate(TASK_ID, arm)

    def test_preflight_uses_browser_backend_in_tv_domain(self):
        from gui_agent_bench.preflight import check

        plan = prepare(
            ROOT,
            {
                'schema': 'run-plan-v1',
                'models': ['reference/solution'],
                'tasks': [{'task': TASK_ID, 'arms': list(ARM_IDS)}],
            },
        )
        with (
            patch('gui_agent_bench.preflight.command', return_value='linux'),
            patch('gui_agent_bench.preflight.check_mobile') as native,
            patch('gui_agent_bench.tv_session.app_mounts') as recorded,
        ):
            result = check(ROOT, plan)
        self.assertEqual(result['status'], 'passed')
        native.assert_not_called()
        recorded.assert_not_called()

    def test_invalid_runtime_returns_preflight_failure_without_guessing_backend(self):
        from gui_agent_bench.preflight import check

        plan = prepare(
            ROOT,
            {
                'schema': 'run-plan-v1',
                'models': ['reference/solution'],
                'tasks': [{'task': TASK_ID, 'arms': ['test_ui']}],
            },
        )
        with (
            patch('gui_agent_bench.preflight.command', return_value='linux'),
            patch('gui_agent_bench.task_runtime.runtime', side_effect=ValueError('invalid runtime')),
        ):
            result = check(ROOT, plan)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(any(c['name'] == 'task_runtime' and c['status'] == 'failed' for c in result['checks']))

    def test_audit_uses_explicit_execution_backend(self):
        from gui_agent_bench.audit import audit_application

        with (
            patch('gui_agent_bench.applications.audit_app', return_value={'status': 'pass'}) as browser,
            patch('gui_agent_bench.tv_session.audit_app') as remote,
        ):
            audit_application(TASK_ID, Path('/recorded-evidence'), platform='web')
        browser.assert_called_once()
        remote.assert_not_called()

    def test_new_tv_domain_task_preserves_execution_platform_without_registration(self):
        spec = importlib.util.spec_from_file_location('task_commands', ROOT / 'scripts/tasks.py')
        commands = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(commands)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(TASK, root / 'tasks' / TASK_ID)
            task = commands.create(root, 'tv/new-aura-behavior', TASK_ID)
            self.assertEqual(runtime(task)['platform'], 'web')
            self.assertEqual(runtime(task)['domain'], 'tv')
            for arm in ARM_IDS:
                reference.validate('tv/new-aura-behavior', arm, root)

    def test_directory_must_match_domain_and_remote_backend_keeps_its_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = root / 'tasks/web' / TASK.name
            shutil.copytree(TASK, task)
            with self.assertRaises(ValueError):
                metadata(task)
            task = root / 'tasks/tv' / TASK.name
            shutil.copytree(TASK, task)
            path = task / 'task.toml'
            path.write_text(path.read_text().replace('platform = "web"', 'platform = "tv"'))
            with self.assertRaisesRegex(ValueError, 'Remote-only TV'):
                metadata(task)

    def test_reference_evidence_records_both_domain_and_backend(self):
        from gui_agent_bench.viewer.evidence import EvidenceIndex
        from gui_agent_bench.viewer.review import Reviewer

        with tempfile.TemporaryDirectory() as temp:
            result = reference.run(ROOT, TASK, 'judge_visual', 'pair', Path(temp))
            folder = Path(result['run_directory'])
            plan = json.loads((folder / 'plan.json').read_text())
            self.assertEqual((plan['domain'], plan['platform']), ('tv', 'web'))
            index = EvidenceIndex(Path(temp))
            row = index.listing()['runs'][0]
            self.assertEqual(row['platform'], 'tv')
            details = Reviewer(index).evaluation(row['id'])
            self.assertEqual((details['platform'], details['execution_platform']), ('tv', 'web'))


if __name__ == '__main__':
    unittest.main()
