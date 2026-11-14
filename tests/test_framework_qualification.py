"""Local qualification cannot outlive changed tasks, images or evidence."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gui_agent_bench import fairness
from gui_agent_bench.io import digest, dump


class QualificationBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.task = 'web/webarena-399-profile-bio'
        self.instruction = self.root / 'tasks' / self.task / 'instruction.md'
        self.instruction.parent.mkdir(parents=True)
        self.instruction.write_text('Public goal')
        (self.instruction.parent / 'task.toml').write_text('[metadata]')
        self.evidence = self.root / '.local/control'
        self.evidence.mkdir(parents=True)
        (self.evidence / 'result.json').write_text('{"passed":true}')
        self.runtime = {'source_lock_sha256': 'source', 'images': {'worker': 'image'}}
        runtime = patch.object(fairness, 'runtime_binding', return_value=self.runtime)
        self.binding = runtime.start()
        self.addCleanup(runtime.stop)
        certificate = {
            'schema': fairness.VERSION,
            'status': 'passed',
            'runtime': self.runtime,
            'task': self.task,
            'task_sha256': fairness.task_binding(self.root, self.task),
            'evidence': {'.local/control/result.json': digest((self.evidence / 'result.json').read_bytes())},
            'evidence_trees': {'.local/control': fairness.evidence_tree(self.root, self.evidence)},
        }
        dump(fairness.certificate_path(self.root, self.task), certificate)

    def test_unchanged_binding_is_accepted_and_added_evidence_is_rejected(self):
        self.assertEqual(fairness.require(self.root, self.task)['status'], 'passed')
        (self.evidence / 'added.txt').write_text('New unbound file')
        with self.assertRaises(ValueError):
            fairness.require(self.root, self.task)

    def test_changed_evidence_or_task_revokes_qualification(self):
        for path in (self.instruction, self.evidence / 'result.json'):
            original = path.read_bytes()
            path.write_bytes(original + b' changed')
            with self.assertRaises(ValueError):
                fairness.require(self.root, self.task)
            path.write_bytes(original)

    def test_changed_image_or_source_and_missing_evidence_fail_closed(self):
        self.binding.return_value = {'source_lock_sha256': 'new-source', 'images': {'worker': 'new-image'}}
        with self.assertRaises(ValueError):
            fairness.require(self.root, self.task)
        self.binding.return_value = self.runtime
        (self.evidence / 'result.json').unlink()
        with self.assertRaises((OSError, ValueError)):
            fairness.require(self.root, self.task)


if __name__ == '__main__':
    unittest.main()
