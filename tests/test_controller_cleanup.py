"""Shutdown faults prevent credit while every owned resource/evidence is finalized."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from contextlib import ExitStack

from gui_agent_bench.controller_cleanup import CleanupFailure, finalize_resources
from gui_agent_bench.failures import Failure, issue
from gui_agent_bench import trial, reference
from gui_agent_bench.verifier import oracle
from gui_agent_bench.verifier.judge import write_result
from gui_agent_bench.io import digest


class ResourceFinalization(unittest.TestCase):
    def test_shutdown_and_log_faults_preserved_and_all_resources_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            session = Mock()
            session.close.side_effect = RuntimeError('private cleanup detail')
            calls = []
            removed = set()
            removed_networks = set()

            def docker(*args, **kwargs):
                calls.append(args)
                if args[:2] == ('logs', 'first'):
                    raise OSError('log unavailable')
                if args[0] == 'logs':
                    return 'retained'
                if args[0] == 'rm':
                    removed.add(args[-1])
                    return ''
                if args[0] == 'ps':
                    return ''
                if args[:2] == ('network', 'rm'):
                    removed_networks.add(args[-1])
                    return ''
                if args[:2] == ('network', 'inspect'):
                    return ''
                return ''

            issues = finalize_resources(
                session,
                ['first', 'second'],
                ['one', 'two'],
                [('first', folder / 'first.log', True), ('second', folder / 'second.log', True)],
                folder,
                docker,
            )
            self.assertEqual([i['operation'] for i in issues], ['native_shutdown', 'collect_logs'])
            self.assertTrue(all(i['impact'] == 'zero_credit' for i in issues))
            self.assertEqual(removed, {'first', 'second'})
            self.assertEqual(removed_networks, {'one', 'two'})
            self.assertEqual((folder / 'second.log').read_text(), 'retained')
            self.assertTrue(all(c['removed'] for c in json.loads((folder / 'cleanup.json').read_text())))
            self.assertNotIn('private cleanup detail', json.dumps(issues))

    def test_one_container_removal_error_does_not_skip_other_containers_or_networks(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            calls = []

            def docker(*args, **kwargs):
                calls.append(args)
                if args[:3] == ('rm', '-f', 'broken'):
                    raise OSError('remove failed')
                return ''

            issues = finalize_resources(None, ['remaining', 'broken'], ['network'], [], folder, docker)
            self.assertEqual(issues[0]['operation'], 'remove_container')
            self.assertIn(('rm', '-f', 'remaining'), calls)
            self.assertIn(('network', 'rm', 'network'), calls)
            records = json.loads((folder / 'cleanup.json').read_text())
            self.assertEqual(
                records, [{'container': 'broken', 'removed': False}, {'container': 'remaining', 'removed': True}]
            )

    def test_trial_wrapper_overwrites_preexisting_pass_and_keeps_all_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            previous = issue(Failure('target_unavailable'), phase='execution', operation='step', impact='zero_credit')
            cleanup = issue(
                Failure('infrastructure_error'), phase='cleanup', operation='native_shutdown', impact='zero_credit'
            )

            def fail(*args, **kwargs):
                write_result(folder / 'logs/verifier', status='graded', reward=1)
                raise CleanupFailure([previous, cleanup])

            with patch.object(trial, '_run_trial', side_effect=fail):
                result = trial.run_trial(folder, folder, folder)
            self.assertEqual(result['reward'], 0)
            self.assertEqual(result['status'], 'trial_error')
            self.assertEqual(result['diagnostics']['issues'], [previous, cleanup])
            self.assertEqual(json.loads((folder / 'logs/verifier/metrics.json').read_text())['reward'], 0)

    def test_reference_trial_keeps_preparation_and_shutdown_causes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / 'tasks/mobile/fake'
            task.mkdir(parents=True)
            first = issue(
                Failure('app_not_ready'), phase='setup', operation='prepare_reference_images', impact='zero_credit'
            )
            second = issue(
                Failure('unknown_operation_error'), phase='cleanup', operation='native_shutdown', impact='zero_credit'
            )
            with (
                patch.object(reference, 'control_for', return_value='fixture'),
                patch.object(reference, 'source_for', return_value='def test(page):\n    pass\n'),
                patch.object(reference, 'needs_reference_images', return_value=True),
                patch.object(reference, 'prepare_references', side_effect=CleanupFailure([first, second])),
            ):
                result = reference.run_trial(root, task, root / 'trial', 'correct', 'test_ui')
            self.assertEqual(result['reward'], 0)
            self.assertEqual(result['diagnostics']['issues'], [first, second])

    def test_completed_oracle_execution_becomes_error_on_shutdown_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / 'task'
            task.mkdir()
            artifact = root / 'test.py'
            artifact.write_text('def test(page):\n    pass\n')
            config = {
                'platform': 'mobile',
                'environment_profile': 'native_extended',
                'viewport_width': 720,
                'viewport_height': 1280,
                'timezone': 'UTC',
                'app_image': 'fixture',
                'reference_timeout_sec': 60,
            }
            session = Mock()
            session.close.side_effect = RuntimeError('cleanup failed')
            records = [
                {'action': {}},
                {'assertion': {'precondition': True}, 'matched': True},
                {'assertion': {'precondition': False}, 'matched': True},
            ]
            removed_networks = set()
            calls = []

            def docker(*args, **kwargs):
                calls.append(args)
                if args[0] == 'logs':
                    return '\n'.join(json.dumps(r) for r in records)
                if args[:2] == ('network', 'rm'):
                    removed_networks.add(args[-1])
                    return ''
                if args[:2] == ('network', 'inspect'):
                    return '' if args[-1] in removed_networks else '[{}]'
                return ''

            process = Mock()
            process.poll.return_value = 0
            with ExitStack() as stack:
                for target, value in [
                    ('gui_agent_bench.verifier.oracle.runtime', config),
                    ('gui_agent_bench.verifier.oracle.start_app', session),
                    ('gui_agent_bench.verifier.oracle.inspect', {'State': {'Running': True, 'ExitCode': 0}}),
                    ('gui_agent_bench.verifier.oracle.reference_digest', 'refs'),
                    ('gui_agent_bench.verifier.oracle.app_isolation', []),
                    ('gui_agent_bench.verifier.oracle.app_mounts', []),
                    ('gui_agent_bench.verifier.oracle.isolation', []),
                    ('gui_agent_bench.verifier.oracle.mount', []),
                    ('gui_agent_bench.verifier.oracle.audit_oracle_broker', None),
                    ('gui_agent_bench.verifier.oracle.audit_execution', {}),
                    ('gui_agent_bench.verifier.oracle.collect_files', None),
                    ('gui_agent_bench.applications.record_app', None),
                    ('gui_agent_bench.audit.audit_broker', None),
                    ('gui_agent_bench.verifier.oracle.subprocess.Popen', process),
                ]:
                    stack.enter_context(patch(target, return_value=value))
                stack.enter_context(patch.object(oracle, 'docker', side_effect=docker))
                folder = root / 'execution'
                result = oracle.execute(
                    task,
                    artifact,
                    folder,
                    'correct',
                    'test_ui',
                    digest(artifact.read_bytes()),
                    references=root / 'references',
                    references_hash='refs',
                )
            self.assertEqual(result['exit_code'], 0)
            self.assertEqual(result['assertions'], records[1:])
            self.assertEqual(result['outcome'], 'ERROR')
            self.assertTrue(result['cleanup_failed'])
            self.assertTrue(any(i['operation'] == 'native_shutdown' for i in result['diagnostics']['issues']))
            self.assertEqual(oracle.pair_result([result, result])['reward'], 0)
            self.assertTrue((folder / 'browser.log').is_file())
            self.assertTrue((folder / 'cleanup.json').is_file())
            self.assertEqual(json.loads((folder / 'result.json').read_text())['outcome'], 'ERROR')
            self.assertTrue(any(c[:2] == ('network', 'rm') for c in calls))
