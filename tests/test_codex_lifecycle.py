import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gui_agent_bench.run_plan import execute
from gui_agent_bench.runners.registry import resolve
from gui_agent_bench.runners.codex import require_qualification, native_boundary

ROOT = Path(__file__).resolve().parents[1]


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch

        qualification = patch('gui_agent_bench.fairness.require')
        qualification.start()
        cohort = patch('gui_agent_bench.fairness.TASKS', ())
        cohort.start()
        self.addCleanup(cohort.stop)
        self.addCleanup(qualification.stop)

    def test_unqualified_runtime_never_starts_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'qualification'):
                require_qualification(Path(folder), resolve('codex/x'), 'judge_visual', 'web')

    def test_native_failure_precise_no_relaxation(self):
        with patch('gui_agent_bench.runners.codex.subprocess.run') as run:
            run.return_value.returncode = 1
            with self.assertRaisesRegex(ValueError, 'user-namespace'):
                native_boundary()
            args = run.call_args.args[0]
            self.assertIn('--cap-drop=ALL', args)
            self.assertNotIn('--privileged', args)
            self.assertFalse(any('unconfined' in a for a in args))

    def test_failed_preflight_keeps_denominator(self):
        spec = json.loads((ROOT / 'jobs/codex-example.json').read_text())
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            path, manifest = execute(
                ROOT,
                spec,
                Path(folder),
                preflight=lambda *_: {'status': 'failed', 'checks': []},
                runner=lambda *a, **k: calls.append(a),
            )
            self.assertEqual(len(manifest['cells']), 6)
            self.assertEqual(calls, [])
            self.assertEqual(manifest['status'], 'preflight_failed')
            self.assertFalse((path / 'resolved-plan.json').exists())

    def test_codex_failure_continues_once(self):
        spec = json.loads((ROOT / 'jobs/codex-example.json').read_text())
        spec['tasks'][0]['arms'] = ['judge_visual', 'judge_test']
        calls = []

        def runner(*args, **kwargs):
            calls.append((args[3], kwargs['agent_spec'].runner))
            raise RuntimeError('synthetic failure')

        with (
            tempfile.TemporaryDirectory() as folder,
            patch('gui_agent_bench.runners.codex_config.resolved', return_value={'schema': 'resolved-plan-v1'}),
            patch('gui_agent_bench.runners.codex.image_ids', return_value={}),
        ):
            _, manifest = execute(
                ROOT, spec, Path(folder), preflight=lambda *_: {'status': 'passed', 'checks': []}, runner=runner
            )
            self.assertEqual(len(calls), 2)
            self.assertEqual(manifest['status'], 'completed_with_errors')
            self.assertEqual([len(c['attempts']) for c in manifest['cells']], [1, 1])
