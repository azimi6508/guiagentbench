"""Whole-run boundary audit: every planned evaluation is reported and can be recorded for the viewer."""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_leakage', ROOT / 'scripts/check_leakage.py')
check_leakage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_leakage)


def plan_run(folder):
    run = Path(folder) / 'run-a'
    cells = []
    for index, (arm, finished) in enumerate([('judge_visual', True), ('test_ui', True), ('oracle_ui', False)]):
        attempt = f'evaluations/{index:04d}/attempt-1'
        path = attempt + (f'/eval{index}' if finished else '')
        (run / path).mkdir(parents=True)
        if finished:
            (run / path / 'plan.json').write_text('{}')
        cells.append({'task': 'web/example', 'arm': arm, 'model': 'fixture/scripted', 'attempts': [{'path': path}]})
    (run / 'run.json').write_text(json.dumps({'cells': cells}))
    return run


class AuditCliTests(unittest.TestCase):
    def invoke(self, *argv, audit):
        output = io.StringIO()
        with (
            patch.object(check_leakage, 'audit_run', side_effect=audit),
            patch.object(sys, 'argv', ['check_leakage.py', *argv]),
            redirect_stdout(output),
        ):
            status = check_leakage.main()
        return status, json.loads(output.getvalue())

    def test_plan_run_reports_every_evaluation_and_records_for_the_viewer(self):
        def audit(directory, _probes):
            if directory.name == 'eval1':
                raise ValueError('workspace arm differs from plan')
            return {'status': 'pass', 'runtime_verified': True}

        with tempfile.TemporaryDirectory() as folder:
            run = plan_run(folder)
            status, summary = self.invoke('--run', str(run), '--record', audit=audit)
            recorded = json.loads((run / 'audits.json').read_text())
        self.assertEqual((status, summary['status'], summary['evaluations'], summary['passed']), (1, 'fail', 3, 1))
        self.assertEqual([row['status'] for row in summary['results']], ['pass', 'fail', 'not_audited'])
        self.assertEqual(summary['results'][1]['reason'], 'workspace arm differs from plan')
        self.assertEqual(
            [r['evaluation'] for r in recorded['results']],
            ['run-a/evaluations/0000/attempt-1/eval0', 'run-a/evaluations/0001/attempt-1/eval1'],
        )
        self.assertEqual([r['returncode'] for r in recorded['results']], [0, 1])
        self.assertEqual(json.loads(recorded['results'][0]['stdout'])['status'], 'pass')

    def test_single_evaluation_keeps_its_report_and_exit_code(self):
        with tempfile.TemporaryDirectory() as folder:
            evaluation = Path(folder) / 'evaluation'
            evaluation.mkdir()
            (evaluation / 'plan.json').write_text('{}')
            status, report = self.invoke('--run', str(evaluation), audit=lambda *_: {'status': 'pass'})
            self.assertEqual((status, report), (0, {'status': 'pass'}))
            status, report = self.invoke('--run', str(evaluation / 'missing'), audit=lambda *_: {'status': 'pass'})
            self.assertEqual((status, report['status']), (1, 'fail'))

    def test_without_a_run_no_runtime_claim_is_made(self):
        status, report = self.invoke(audit=lambda *_: {})
        self.assertEqual((status, report['status'], report['runtime_verified']), (2, 'not_run', False))


if __name__ == '__main__':
    unittest.main()


class MovedEvidenceTests(unittest.TestCase):
    """Recorded runs stay auditable after they are copied or cloned to another folder."""

    def setUp(self):
        from gui_agent_bench.io import recorded_evidence, same_source

        self.recorded_evidence, self.same_source = recorded_evidence, same_source
        self.folder = tempfile.TemporaryDirectory()
        self.run = Path(self.folder.name) / 'runs' / 'abc'
        self.config = self.run / 'evaluations/0001/attempt-1/x/trials/0123456789abcdef/config'
        self.config.mkdir(parents=True)
        (self.run / 'run.json').write_text('{}')
        (self.run / 'evaluations/0001/attempt-1/x/plan.json').write_text('{}')
        self.recorded = '/elsewhere/github-release/runs/abc/evaluations/0001/attempt-1/x/trials/0123456789abcdef/config'

    def tearDown(self):
        self.folder.cleanup()

    def test_live_checks_require_the_exact_host_path(self):
        self.assertTrue(self.same_source(str(self.config), self.config))
        self.assertFalse(self.same_source(self.recorded, self.config))

    def test_recorded_audit_accepts_the_same_path_below_a_moved_run(self):
        with self.recorded_evidence():
            self.assertTrue(self.same_source(self.recorded, self.config))
        self.assertFalse(self.same_source(self.recorded, self.config))

    def test_recorded_audit_still_rejects_a_different_source(self):
        other = self.recorded.replace('0123456789abcdef', 'fedcba9876543210')
        with self.recorded_evidence():
            self.assertFalse(self.same_source(other, self.config))
            self.assertFalse(self.same_source(self.recorded + '/extra', self.config))
            self.assertFalse(self.same_source('/elsewhere/config', self.config))
            self.assertFalse(self.same_source('/tmp/outside/config', Path(self.folder.name) / 'loose/config'))
