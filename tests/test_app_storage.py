"""A task may declare a disposable writable app layer; nothing else loosens."""

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from gui_agent_bench.applications import audit_app
from gui_agent_bench.io import dump
from gui_agent_bench.task_runtime import WRITABLE_ROOT_LABEL, app_isolation, runtime

EXAMPLE = ROOT / 'tasks/web/webarena-399-profile-bio'


def container(read_only, labels=None):
    return {
        'HostConfig': {
            'ReadonlyRootfs': read_only,
            'Privileged': False,
            'CapDrop': ['ALL'],
            'SecurityOpt': ['no-new-privileges'],
        },
        'Config': {'User': 'postgres', 'Labels': labels or {}},
        'NetworkSettings': {'Networks': {'capture': {}}, 'Ports': {}},
        'Mounts': [{'Type': 'bind', 'Destination': '/settings.json', 'RW': False}],
    }


class AppStorage(unittest.TestCase):
    def test_declared_writable_root_drops_only_read_only_flag(self):
        config = runtime(EXAMPLE)
        self.assertIs(config['app_writable_root'], True)
        flags = app_isolation(EXAMPLE, config)
        default = app_isolation(EXAMPLE, {**config, 'app_writable_root': False})
        self.assertNotIn('--read-only', flags)
        self.assertIn('--read-only', default)
        self.assertEqual(
            [f for f in flags if f not in ('--label', WRITABLE_ROOT_LABEL)], [f for f in default if f != '--read-only']
        )
        self.assertEqual(flags[-2:], ['--label', WRITABLE_ROOT_LABEL])

    def test_other_examples_keep_read_only_root(self):
        for task in ('tv/aura-013-caption-preview-size', 'mobile/markor-note-persistence'):
            config = runtime(ROOT / 'tasks' / task)
            self.assertIs(config['app_writable_root'], False)
            self.assertIn('--read-only', app_isolation(ROOT / 'tasks' / task, config))

    def test_setting_must_be_boolean(self):
        with tempfile.TemporaryDirectory() as temp:
            task = Path(temp) / 'tasks/web' / EXAMPLE.name
            shutil.copytree(EXAMPLE, task)
            path = task / 'task.toml'
            path.write_text(path.read_text().replace('app_writable_root = true', 'app_writable_root = "yes"'))
            with self.assertRaisesRegex(ValueError, 'boolean'):
                runtime(task)

    def test_audit_accepts_writable_root_only_when_declared(self):
        key, value = WRITABLE_ROOT_LABEL.split('=')
        cases = [
            (container(True), True),
            (container(False, {key: value}), True),
            (container(False), False),
            (container(True, {key: value}), False),
        ]
        for app, accepted in cases:
            with (
                self.subTest(read_only=app['HostConfig']['ReadonlyRootfs'], labels=app['Config']['Labels']),
                tempfile.TemporaryDirectory() as temp,
            ):
                folder = Path(temp)
                dump(folder / 'app-container.json', app)
                dump(folder / 'app-network.json', {'Name': 'capture', 'Internal': True})
                if accepted:
                    result = audit_app(folder)
                    self.assertEqual(result['read_only_root'], app['HostConfig']['ReadonlyRootfs'])
                else:
                    with self.assertRaises(ValueError):
                        audit_app(folder)

    def test_writable_root_does_not_relax_other_boundaries(self):
        key, value = WRITABLE_ROOT_LABEL.split('=')
        for change in ({'Privileged': True}, {'CapDrop': []}):
            app = container(False, {key: value})
            app['HostConfig'].update(change)
            with self.subTest(change=json.dumps(change)), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                dump(folder / 'app-container.json', app)
                dump(folder / 'app-network.json', {'Name': 'capture', 'Internal': True})
                with self.assertRaises(ValueError):
                    audit_app(folder)


if __name__ == '__main__':
    unittest.main()
