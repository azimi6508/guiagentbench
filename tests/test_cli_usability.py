"""First-run CLI behavior: advertised commands and actionable errors."""

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gui_agent_bench import preflight
from gui_agent_bench.cli import main, parser
from gui_agent_bench.docker import AGENT_IMAGE, ORACLE_BROWSER_IMAGE, ORACLE_IMAGE, WORKER_IMAGE
from gui_agent_bench.viewer.app import main as viewer

ROOT = Path(__file__).resolve().parents[1]
WEB = 'web/webarena-399-profile-bio'
APP = 'gui-agent-bench-public-webarena:399'


def docker(present):
    """A stand-in for the Docker CLI that knows a fixed set of local images."""
    asked = []

    def command(*args, **_):
        if args[:2] == ('docker', 'info'):
            return 'linux'
        asked.append(args[3].removeprefix('docker.io/library/'))
        if asked[-1] not in present:
            raise subprocess.CalledProcessError(1, args)
        return 'sha256:id'

    return command, asked


class CliUsabilityTests(unittest.TestCase):
    def run_cli(self, *argv):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(list(argv))
        return status, json.loads(output.getvalue())

    def test_help_lists_only_user_commands(self):
        text = parser().format_help()
        for name in ('build', 'run', 'verify', 'verify-oracle', 'verify-test'):
            self.assertIn(name, text)
        self.assertNotIn('_gateway', text)
        self.assertNotIn('_broker', text)
        parser().parse_args(['_gateway', '--provider', 'fixture', '--model', 'scripted'])

    def test_unknown_task_names_the_available_tasks(self):
        status, result = self.run_cli('run', '--task', 'web/nope', '--arm', 'test_ui', '--model', 'reference/solution')
        self.assertEqual(status, 1)
        self.assertIn("Unknown task 'web/nope'", result['reason'])
        self.assertIn(WEB, result['reason'])

    def test_unknown_arm_is_rejected_by_the_parser(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            parser().parse_args(['run', '--task', WEB, '--arm', 'test_gui', '--model', 'reference/solution'])

    def test_missing_images_report_the_build_command(self):
        command, asked = docker({WORKER_IMAGE, ORACLE_IMAGE, ORACLE_BROWSER_IMAGE})
        with patch.object(preflight, 'command', command):
            with self.assertRaisesRegex(
                ValueError, f'not built: {APP}. Build them with: python scripts/bench.py build --task {WEB}$'
            ):
                preflight.require_runtime(ROOT, WEB, 'test_ui', 'reference/solution')
        self.assertEqual(sorted(asked), sorted([WORKER_IMAGE, ORACLE_IMAGE, ORACLE_BROWSER_IMAGE, APP]))
        command, asked = docker({WORKER_IMAGE, ORACLE_IMAGE, ORACLE_BROWSER_IMAGE, APP})
        with patch.object(preflight, 'command', command):
            preflight.require_runtime(ROOT, WEB, 'test_ui', 'reference/solution')
            with self.assertRaisesRegex(ValueError, AGENT_IMAGE):
                preflight.require_runtime(ROOT, WEB, 'test_ui', 'fixture/scripted')
            with self.assertRaisesRegex(ValueError, '--runner all'):
                preflight.require_runtime(ROOT, WEB, 'judge_visual', 'claude/claude-model')

    def test_reference_judgment_needs_no_container(self):
        def unavailable(*_, **__):
            raise FileNotFoundError('docker')

        with patch.object(preflight, 'command', unavailable):
            preflight.require_runtime(ROOT, WEB, 'judge_visual', 'reference/solution')
            with self.assertRaisesRegex(ValueError, 'Docker is not available'):
                preflight.require_runtime(ROOT, WEB, 'oracle_ui', 'reference/solution')

    def test_viewer_explains_a_missing_runs_directory(self):
        errors = io.StringIO()
        with tempfile.TemporaryDirectory() as folder, redirect_stderr(errors):
            self.assertEqual(viewer([str(Path(folder) / 'runs'), '--no-open']), 1)
        self.assertIn('is not a directory. Run an evaluation first', errors.getvalue())

    def test_verify_never_grades_over_an_existing_result(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'judgment.json').write_text('{"verdict":"PASS"}')
            (folder / 'labels.json').write_text('{"correct": "PASS", "faulty": "FAIL"}')
            command = [
                'verify',
                '--submission',
                str(folder / 'judgment.json'),
                '--labels',
                str(folder / 'labels.json'),
                '--variant',
                'correct',
                '--output',
                str(folder / 'out'),
            ]
            status, first = self.run_cli(*command)
            self.assertEqual((status, first['reward']), (0, 1))
            status, second = self.run_cli(*command[:-3], 'faulty', '--output', str(folder / 'out'))
            self.assertEqual(status, 1)
            self.assertIn('already holds a result', second['reason'])
            self.assertEqual((folder / 'out/reward.txt').read_text(), '1\n')

    def test_deeply_nested_judgment_is_malformed_not_a_verifier_error(self):
        from gui_agent_bench.verifier.judge import grade

        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'judgment.json').write_text('[' * 16000)
            (folder / 'labels.json').write_text('{"correct": "PASS", "faulty": "FAIL"}')
            result = grade(folder / 'judgment.json', folder / 'labels.json', 'correct', folder / 'out')
        self.assertEqual((result['status'], result['reward']), ('invalid_submission', 0))

    def test_invalid_task_folder_is_named(self):
        from gui_agent_bench.task_package import discover

        with tempfile.TemporaryDirectory() as folder:
            draft = Path(folder) / 'tasks/web/My_Draft'
            draft.mkdir(parents=True)
            (draft / 'task.toml').write_text('')
            with self.assertRaisesRegex(ValueError, 'Invalid task folder tasks/web/My_Draft'):
                discover(folder)

    def test_openrouter_run_explains_a_missing_key(self):
        with patch.dict('os.environ', {}, clear=False) as environment:
            environment.pop('OPENROUTER_API_KEY', None)
            with self.assertRaisesRegex(ValueError, 'OPENROUTER_API_KEY is not set'):
                preflight.require_runtime(ROOT, WEB, 'judge_visual', 'openrouter/provider/model')

    def test_termination_unwinds_like_an_interrupt(self):
        import os
        import signal
        from gui_agent_bench.entrypoint import interrupt_on_termination

        previous = {name: signal.getsignal(getattr(signal, name)) for name in ('SIGTERM', 'SIGHUP')}
        try:
            interrupt_on_termination()
            for name in previous:
                with self.assertRaises(KeyboardInterrupt):
                    os.kill(os.getpid(), getattr(signal, name))
                    signal.pause()
        finally:
            for name, handler in previous.items():
                signal.signal(getattr(signal, name), handler)


if __name__ == '__main__':
    unittest.main()
