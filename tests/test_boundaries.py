"""Meaningful admission, scoring and isolation regressions; stdlib unittest only."""

import json
from pathlib import Path
import tempfile
import unittest
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from gui_agent_bench.gateway import fixture_reply
from gui_agent_bench.io import digest, dump, regular_file
from gui_agent_bench.materialize import materialize, validate_workspace
from gui_agent_bench.runners.opencode import validate_events
from gui_agent_bench.failures import Failure
from gui_agent_bench.trial import _prepare_verifier_logs
from gui_agent_bench.verifier.judge import aggregate, grade, write_result


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gui-agent-bench-public-test-')
        self.root = Path(self.temporary.name).resolve()
        self.labels = self.root / 'labels.json'
        dump(self.labels, {'correct': 'PASS', 'faulty': 'FAIL'})

    def tearDown(self):
        # TemporaryDirectory owns exactly this resolved directory, never the workspace.
        assert self.root.parent == Path(tempfile.gettempdir()).resolve()
        assert self.root.name.startswith('gui-agent-bench-public-test-')
        self.temporary.cleanup()

    def grade(self, data, variant='correct'):
        submission = self.root / 'judgment.json'
        if data is not None:
            submission.write_bytes(data)
        return grade(submission, self.labels, variant, self.root / 'logs')

    def test_prediction_is_graded_against_private_label(self):
        self.assertEqual(self.grade(b'{"verdict":"PASS"}')['reward'], 1)
        self.assertEqual(self.grade(b'{"verdict":"PASS"}', 'faulty')['reward'], 0)
        self.assertEqual(self.grade(b'{"verdict":"FAIL"}', 'faulty')['reward'], 1)

    def test_missing_abstaining_duplicate_and_extra_fields_are_wrong(self):
        for data in (
            None,
            b'{}',
            b'{"verdict":"ABSTAIN"}',
            b'{"verdict":"FAIL","verdict":"PASS"}',
            b'{"verdict":"PASS","reward":1}',
            b'not json',
            b'[]',
            b'{"verdict":"PASS","reason":false}',
        ):
            with self.subTest(data=data):
                result = self.grade(data)
                self.assertEqual(result['status'], 'invalid_submission')
                self.assertEqual(result['reward'], 0)
                self.assertEqual((self.root / 'logs/reward.txt').read_text(), '0\n')

    def test_verdict_check_has_the_five_second_judgment_limit(self):
        import time
        from unittest import mock
        from gui_agent_bench import budgets
        from gui_agent_bench.verifier import judge

        self.assertEqual(budgets.JUDGMENT_CHECK_SECONDS, 5)
        with (
            mock.patch.object(judge, 'JUDGMENT_CHECK_SECONDS', 0.05),
            mock.patch.object(judge, 'check', side_effect=lambda *_: time.sleep(2)),
        ):
            result = self.grade(b'{"verdict":"PASS"}')
        self.assertEqual((result['status'], result['reward']), ('verifier_error', 0))
        self.assertEqual(result['diagnostics']['issues'][0]['cause'], 'infrastructure_error')
        self.assertEqual(self.grade(b'{"verdict":"PASS"}')['reward'], 1)

    def test_oversized_submission_fails_closed(self):
        self.assertEqual(self.grade(b' ' * 16385)['status'], 'invalid_submission')

    def test_planned_denominator_includes_missing_trials(self):
        summary = aggregate([{'status': 'graded', 'reward': 1}], 2, True)
        self.assertEqual(summary['accuracy'], 0.5)
        self.assertEqual(summary['paired_score'], 0)
        self.assertEqual(summary['invalid_or_missing'], 1)

    def test_planned_results_are_writable_by_the_fixed_worker_uid(self):
        output = self.root / 'worker-output'
        write_result(output, status='planned')
        _prepare_verifier_logs(output)
        self.assertEqual(output.stat().st_mode & 0o777, 0o777)
        for name in ('reward.txt', 'reward.json', 'metrics.json'):
            self.assertEqual((output / name).stat().st_mode & 0o777, 0o666)

    def evidence(self):
        evidence = self.root / 'capture'
        evidence.mkdir()
        frames = []
        for index in range(1, 4):
            relative = f'screenshots/{index:04d}.png'
            path = evidence / relative
            path.parent.mkdir(exist_ok=True)
            data = b'\x89PNG\r\n\x1a\n' + bytes([index])
            path.write_bytes(data)
            frames.append({'path': relative, 'index': index, 'sha256': digest(data)})
        dump(evidence / 'manifest.json', {'frames': frames})
        dump(evidence / 'steps.json', ['initial', 'add', 'reload'])
        (evidence / 'private-labels.txt').write_text('must never be copied')
        return evidence

    def test_only_explicit_evidence_files_are_materialized(self):
        workspace = self.root / 'workspace'
        manifest = materialize(
            ROOT, ROOT / 'tasks/web/webarena-399-profile-bio', self.evidence(), workspace, 'judge_visual'
        )
        self.assertEqual(len(manifest['files']), 6)
        self.assertFalse((workspace / 'private-labels.txt').exists())
        validate_workspace(workspace, manifest)
        (workspace / 'evidence/manifest.json').write_text('{}')
        with self.assertRaises(ValueError):
            validate_workspace(workspace, manifest)

    def test_missing_or_reordered_frames_fail(self):
        evidence = self.evidence()
        manifest = json.loads((evidence / 'manifest.json').read_text())
        manifest['frames'].reverse()
        dump(evidence / 'manifest.json', manifest)
        with self.assertRaises(ValueError):
            materialize(
                ROOT, ROOT / 'tasks/web/webarena-399-profile-bio', evidence, self.root / 'workspace', 'judge_visual'
            )

    def test_explicit_web_checkpoint_count_preserves_complete_evidence(self):
        import shutil

        task = self.root / 'task'
        shutil.copytree(ROOT / 'tasks/web/webarena-399-profile-bio', task)
        task_file = task / 'task.toml'
        task_file.write_text(task_file.read_text().replace('checkpoints = 3', 'checkpoints = 5'))
        evidence = self.evidence()
        manifest = json.loads((evidence / 'manifest.json').read_text())
        for index in (4, 5):
            name = f'screenshots/{index:04d}.png'
            data = b'\x89PNG\r\n\x1a\n' + bytes([index])
            (evidence / name).write_bytes(data)
            manifest['frames'].append({'path': name, 'index': index, 'sha256': digest(data)})
        dump(evidence / 'manifest.json', manifest)
        dump(evidence / 'steps.json', ['step'] * 5)
        result = materialize(ROOT, task, evidence, self.root / 'five', 'judge_visual')
        self.assertEqual(len(result['files']), 8)
        for frames in (manifest['frames'][:-1], list(reversed(manifest['frames']))):
            dump(evidence / 'manifest.json', {'frames': frames})
            with self.assertRaises(ValueError):
                materialize(ROOT, task, evidence, self.root / 'invalid', 'judge_visual')

    def test_unknown_arm_and_path_escape_are_rejected(self):
        with self.assertRaises(ValueError):
            materialize(ROOT, ROOT, self.root, self.root / 'workspace', 'unknown_arm')
        with self.assertRaises(ValueError):
            regular_file(ROOT / 'README.md', self.root)

    def test_symbolic_link_is_not_a_submission(self):
        link = self.root / 'judgment.json'
        try:
            link.symlink_to(self.labels)
        except OSError:
            self.skipTest('host does not permit symbolic links')
        self.assertEqual(grade(link, self.labels, 'correct', self.root / 'logs')['status'], 'invalid_submission')

    def test_fixture_is_label_independent(self):
        message, _ = fixture_reply([], 'PASS', False)
        self.assertEqual(message['tool_calls'][0]['function']['name'], 'read')
        # The scripted provider accepts no variant or expected-label argument.
        messages = [{'role': 'assistant', 'tool_calls': [{}] * 5}]
        message, _ = fixture_reply(messages, 'PASS', False)
        artifact = json.loads(message['tool_calls'][0]['function']['arguments'])
        self.assertEqual(json.loads(artifact['content'])['verdict'], 'PASS')

    def test_fixture_can_omit_submission_without_faking_an_artifact(self):
        messages = [{'role': 'assistant', 'tool_calls': [{}] * 5}]
        message, reason = fixture_reply(messages, 'MISSING', False)
        self.assertEqual(reason, 'stop')
        self.assertNotIn('tool_calls', message)

    def test_incomplete_and_truncated_trajectories_are_rejected(self):
        finish = {'type': 'step_finish', 'part': {'reason': 'stop'}}
        validate_events([finish])
        for events in (
            [],
            [{'type': 'step_finish', 'part': {'reason': 'tool-calls'}}],
            [{'type': 'error'}, finish],
            [{'type': 'tool_use', 'part': {'metadata': {'truncated': True}}}, finish],
            [{'type': 'compaction'}, finish],
            [{'type': 'step_finish', 'part': {'reason': 'length'}}, finish],
        ):
            with self.subTest(events=events), self.assertRaises(Failure):
                validate_events(events)


if __name__ == '__main__':
    unittest.main()
