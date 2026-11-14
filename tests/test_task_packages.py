"""New packages integrate without shared registries or privileged code imports."""

import importlib.util
import json
import os
import subprocess
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gui_agent_bench import reference
from gui_agent_bench.io import digest
from gui_agent_bench.task_package import discover, task_path, verify, seal_manifest, local_file, load_control

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('task_commands', ROOT / 'scripts/tasks.py')
commands = importlib.util.module_from_spec(spec)
spec.loader.exec_module(commands)


class TaskPackages(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = 'web/webarena-399-profile-bio'
        shutil.copytree(ROOT / 'tasks' / self.source, self.root / 'tasks' / self.source)

    def test_new_package_is_discovered_planned_and_referenced_without_source_edits(self):
        from gui_agent_bench.run_plan import prepare

        task = commands.create(self.root, 'web/new-behavior', self.source)
        self.assertEqual(set(discover(self.root)), {self.source, 'web/new-behavior'})
        verify(task)
        plan = commands.plan(self.root, ['web/new-behavior'], None, 'reference/solution', self.root / 'plan.json')
        self.assertEqual(len(prepare(self.root, plan)['cells']), 6)
        for arm in ('judge_visual', 'judge_test', 'oracle_visual', 'oracle_ui', 'test_visual', 'test_ui'):
            reference.validate('web/new-behavior', arm, self.root)
        self.assertEqual(reference.control_for('web/new-behavior', self.root), 'web/new-behavior')
        self.assertEqual(set(p.name for p in self.root.iterdir()), {'tasks', 'plan.json'})
        with self.assertRaises(ValueError):
            commands.create(self.root, 'web/new-behavior', self.source)

    def test_reference_shortcut_uses_its_own_package_and_forwards_run_options(self):
        from gui_agent_bench.task_package import discover

        for identifier in discover(ROOT):
            if not (ROOT / 'tasks' / identifier / 'solution/solve.sh').is_file():
                continue
            with self.subTest(task=identifier), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / 'checkout with spaces'
                source = root / 'tasks' / identifier
                shutil.copytree(ROOT / 'tasks' / identifier, source)
                slug = identifier.split('/')[0] + '/renamed-behavior'
                task = commands.create(root, slug, identifier)
                shim = Path(temp) / 'bin'
                shim.mkdir()
                executable = shim / 'python3'
                executable.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@"\n')
                executable.chmod(0o755)
                result = subprocess.run(
                    ['sh', str(task / 'solution/solve.sh'), 'judge_test', '--output', 'output with spaces'],
                    env=dict(os.environ, PATH=str(shim) + os.pathsep + os.environ['PATH']),
                    check=True,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(
                    result.stdout.splitlines(),
                    [
                        str(root / 'scripts/bench.py'),
                        'run',
                        '--task',
                        slug,
                        '--model',
                        'reference/solution',
                        '--arm',
                        'judge_test',
                        '--output',
                        'output with spaces',
                    ],
                )

    def test_clone_accepts_valid_compact_metadata_formatting(self):
        source = task_path(self.root, self.source)
        path = source / 'task.toml'
        path.write_text(
            path.read_text()
            .replace('name = ', 'name=')
            .replace('task_id = ', 'task_id=')
            .replace('reference_alias = ', 'reference_alias=')
        )
        seal_manifest(source)
        task = commands.create(self.root, 'web/compact-clone', self.source)
        self.assertEqual(verify(task)['task'], 'web/compact-clone')

    def test_manifest_detects_additions_changes_and_links(self):
        task = task_path(self.root, self.source)
        goal = task / 'instruction.md'
        goal.write_text(goal.read_text() + '\nUpdated behavior')
        with self.assertRaisesRegex(ValueError, 'Task files changed'):
            verify(task)
        seal_manifest(task)
        verify(task)
        extra = task / 'unexpected.txt'
        extra.write_text('unsealed input')
        with self.assertRaises(ValueError):
            verify(task)
        extra.unlink()
        extra.symlink_to(self.root / 'outside')
        with self.assertRaises((ValueError, OSError)):
            seal_manifest(task)

    def test_reference_is_data_and_cannot_escape_package(self):
        task = task_path(self.root, self.source)
        source = task / 'solution/test_ui.py'
        marker = self.root / 'should-not-exist'
        source.write_text(
            'from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\ndef test(page):\n    return True\n'
        )
        load_control(task)
        self.assertFalse(marker.exists())
        for path in ('../outside', '/private/key', 'solution/../../outside'):
            with self.assertRaises(ValueError):
                local_file(task, path)
        record = json.loads((task / 'private/reference.json').read_text())
        record['programs']['test_ui'] = '../outside.py'
        (task / 'private/reference.json').write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            load_control(task)

    def test_metadata_identity_and_arm_membership_are_enforced(self):
        task = task_path(self.root, self.source)
        text = (task / 'task.toml').read_text()
        (task / 'task.toml').write_text(text.replace('task_id = "webarena-399-profile-bio"', 'task_id = "other"'))
        with self.assertRaises(ValueError):
            verify(task)
        (task / 'task.toml').write_text(text.replace('"test_ui", ', '').replace(', "test_ui"', ''))
        with self.assertRaises(ValueError):
            reference.validate(self.source, 'test_ui', self.root)

    def test_reference_viewport_must_match_runtime(self):
        task = task_path(self.root, self.source)
        path = task / 'private/reference.json'
        record = json.loads(path.read_text())
        record['viewport'] = [960, 640]
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'viewport differs'):
            load_control(task)

    def test_fixture_provider_cannot_gain_extra_mounts_or_credentials(self):
        import copy
        from gui_agent_bench.audit import audit_fixture_provider
        from gui_agent_bench.task_package import load_control

        folder = self.root / 'trial'
        folder.mkdir()
        (folder / 'fixture-control.json').write_text(json.dumps(load_control(task_path(self.root, self.source))))
        details = {
            'HostConfig': {
                'ReadonlyRootfs': True,
                'Privileged': False,
                'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges'],
            },
            'NetworkSettings': {'Networks': {'isolated': {}}},
            'Config': {'Env': ['PATH=/usr/bin']},
            'Mounts': [
                {
                    'Type': 'bind',
                    'RW': False,
                    'Destination': '/fixture-control.json',
                    'Source': str(folder / 'fixture-control.json'),
                }
            ],
        }
        audit_fixture_provider(details, folder, 'isolated')
        for mutation in ('writable', 'extra-mount', 'internet', 'credential'):
            changed = copy.deepcopy(details)
            if mutation == 'writable':
                changed['Mounts'][0]['RW'] = True
            elif mutation == 'extra-mount':
                changed['Mounts'].append({'Type': 'bind', 'RW': False, 'Destination': '/private', 'Source': '/private'})
            elif mutation == 'internet':
                changed['NetworkSettings']['Networks']['bridge'] = {}
            else:
                changed['Config']['Env'].append('OPENROUTER_API_KEY=synthetic')
            with self.assertRaises(ValueError):
                audit_fixture_provider(changed, folder, 'isolated')

    def test_native_application_pin_is_checked_before_hook_import(self):
        from gui_agent_bench.native_application import declared_application, verify_installed

        task = self.root / 'tasks/mobile/new-app'
        task.mkdir(parents=True)
        source = task / 'application.py'
        source.write_text('raise RuntimeError("must not import during discovery")\n')
        (task / 'task.toml').write_text(
            '''[metadata]
task_id="new-app"
platform="mobile"
eligible_arms=["test_ui"]
source="local"
upstream_id="local"
upstream_url="local:example"
upstream_revision="1"
license="Apache-2.0"
transform_notes="test fixture"
[integration]
native_application="application.py"
native_package="org.example.app"
native_apk_sha256="'''
            + 'a' * 64
            + '"\n'
        )
        record = declared_application(self.root, 'mobile/new-app')
        self.assertEqual(record['source_sha256'], digest(source.read_bytes()))
        with (
            patch('gui_agent_bench.mobile_driver.safe_device') as safe,
            patch(
                'gui_agent_bench.mobile_driver.adb',
                side_effect=['package:/data/app/sample/base.apk', 'a' * 64 + ' file'],
            ),
        ):
            self.assertEqual(verify_installed(self.root, 'mobile/new-app'), record)
            safe.assert_called_once()
        for outputs in (['package:/sdcard/base.apk'], ['package:/data/app/sample/base.apk', 'b' * 64]):
            with (
                patch('gui_agent_bench.mobile_driver.safe_device'),
                patch('gui_agent_bench.mobile_driver.adb', side_effect=outputs),
                self.assertRaises(ValueError),
            ):
                verify_installed(self.root, 'mobile/new-app')


if __name__ == '__main__':
    unittest.main()
