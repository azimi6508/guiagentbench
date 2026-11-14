"""App behavior belongs to task fixtures; platform safety remains shared."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from gui_agent_bench import mobile_driver, native_application, mobile_runtime
from gui_agent_bench.task_package import seal_manifest, verify
from gui_agent_bench.io import digest

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / 'tasks/mobile/markor-note-persistence'


def task_module():
    module = types.ModuleType('example_task_fixture')
    path = TASK / 'environment/application.py'
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


class TaskFixtureBoundary(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.task = self.root / 'tasks/mobile/other-app'
        shutil.copytree(TASK, self.task)
        metadata = self.task / 'task.toml'
        text = metadata.read_text().replace('task_id = "markor-note-persistence"', 'task_id = "other-app"')
        text = text.replace('native_package = "net.gsantner.markor"', 'native_package = "org.example.reader"')
        metadata.write_text(text)
        self.settings = {'workspace': ['section-a'], 'simulate': {'color': 'violet'}}
        for variant in ('correct', 'faulty'):
            (self.task / 'variants' / variant / 'settings.json').write_text(json.dumps(self.settings))
        self.fixture = self.task / 'environment/application.py'
        self.fixture.write_text(
            '''class Application:
    def __init__(self, settings):
        self.received = settings
    def reset(self, device, adb): pass
    def launch(self, device, adb): pass
    def reload(self, device, adb): pass
'''
        )
        seal_manifest(self.task)

    def test_unrelated_configuration_is_owned_by_the_fixture(self):
        record = native_application.declared_application(self.root, 'mobile/other-app')
        with patch.object(native_application, 'verify_installed', return_value=record):
            fixture, bound = native_application.load_fixture(self.root, 'mobile/other-app', 'correct')
        self.assertEqual(fixture.received, self.settings)
        self.assertEqual(bound['package'], 'org.example.reader')
        self.assertEqual(bound['settings_sha256'], digest((self.task / 'variants/correct/settings.json').read_bytes()))

    def test_fixture_has_normal_module_context_without_shared_variant_globals(self):
        self.fixture.write_text(
            """from __future__ import annotations
from dataclasses import dataclass
@dataclass
class Application:
    settings: dict
    def reset(self, device, adb): pass
    def launch(self, device, adb): pass
    def reload(self, device, adb): pass
"""
        )
        seal_manifest(self.task)
        record = native_application.declared_application(self.root, 'mobile/other-app')
        with patch.object(native_application, 'verify_installed', return_value=record):
            first, _ = native_application.load_fixture(self.root, 'mobile/other-app', 'correct')
            second, _ = native_application.load_fixture(self.root, 'mobile/other-app', 'faulty')
        self.assertEqual(first.settings, self.settings)
        self.assertIsNot(type(first), type(second))
        self.assertIn(type(first).__module__, sys.modules)
        self.assertNotEqual(type(first).__module__, type(second).__module__)

    def test_discovery_and_validation_never_execute_task_fixture(self):
        marker = self.root / 'executed'
        self.fixture.write_text(
            'from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n' + self.fixture.read_text()
        )
        seal_manifest(self.task)
        verify(self.task)
        self.assertFalse(marker.exists())
        with patch.object(native_application, 'verify_installed', side_effect=ValueError('APK pin differs')):
            with self.assertRaises(ValueError):
                native_application.load_fixture(self.root, 'mobile/other-app', 'correct')
        self.assertFalse(marker.exists())

    def test_tampering_and_invalid_variant_fail_before_loading(self):
        with patch.object(native_application, 'verify_installed') as installed:
            with self.assertRaises(ValueError):
                native_application.load_fixture(self.root, 'mobile/other-app', '../private')
            installed.assert_not_called()
            self.fixture.write_text(self.fixture.read_text() + '\n# unsealed change\n')
            with self.assertRaises(ValueError):
                native_application.load_fixture(self.root, 'mobile/other-app', 'correct')
            installed.assert_not_called()

    def test_changed_application_declaration_is_rejected_before_import(self):
        record = native_application.declared_application(self.root, 'mobile/other-app')
        record['package'] = 'org.example.different'
        with patch.object(native_application, 'verify_installed', return_value=record):
            with self.assertRaisesRegex(ValueError, 'declaration changed'):
                native_application.load_fixture(self.root, 'mobile/other-app', 'correct')

    def test_mobile_package_cannot_select_a_builtin_fallback(self):
        metadata = self.task / 'task.toml'
        text = '\n'.join(line for line in metadata.read_text().splitlines() if not line.startswith('native_'))
        metadata.write_text(text)
        with self.assertRaises(ValueError):
            seal_manifest(self.task)
        with patch.object(mobile_driver, 'safe_device') as safe:
            with self.assertRaises(ValueError):
                mobile_driver.Driver(self.root, None, None)
            safe.assert_not_called()

    def test_incorrect_apk_file_is_rejected_before_device_install(self):
        source = self.root / 'application.apk'
        source.write_bytes(b'not the pinned APK')
        with patch.object(mobile_driver, 'safe_device') as safe, patch.object(mobile_driver, 'adb') as adb:
            with self.assertRaises(ValueError):
                native_application.install_apk(self.root, 'mobile/other-app', source)
            safe.assert_not_called()
            adb.assert_not_called()

    def test_missing_application_has_an_explicit_setup_error(self):
        with (
            patch.object(mobile_driver, 'safe_device'),
            patch.object(mobile_driver, 'adb', side_effect=subprocess.CalledProcessError(1, ['adb'])),
        ):
            with self.assertRaisesRegex(ValueError, 'application is unavailable'):
                native_application.verify_installed(self.root, 'mobile/other-app')

    def test_system_application_is_pinned_without_a_default_app(self):
        record = native_application.declared_application(self.root, 'mobile/other-app')
        with (
            patch.object(mobile_driver, 'safe_device'),
            patch.object(
                mobile_driver,
                'adb',
                side_effect=['package:/system/priv-app/Reader/Reader.apk', record['apk_sha256'] + ' file'],
            ),
        ):
            self.assertEqual(native_application.verify_installed(self.root, 'mobile/other-app'), record)


class GenericDriverLifecycle(unittest.TestCase):
    def driver(self):
        driver = object.__new__(mobile_driver.Driver)
        driver.package = 'org.example.reader'
        driver.device = Mock()
        driver.application = types.SimpleNamespace(reset=Mock(), launch=Mock(), reload=Mock())
        driver.settle = Mock()
        return driver

    def test_launch_and_reload_delegate_without_task_data(self):
        driver = self.driver()
        with (
            patch.object(mobile_driver, 'wait_focused_package') as focused,
            patch.object(mobile_driver, 'focused_package', return_value=driver.package),
        ):
            driver.launch()
            driver.reload()
        driver.application.launch.assert_called_once_with(driver.device, mobile_driver.adb)
        driver.application.reload.assert_called_once_with(driver.device, mobile_driver.adb)
        self.assertEqual(focused.call_count, 2)
        driver.device.push.assert_not_called()
        self.assertFalse(hasattr(driver, 'settings'))

    def test_reset_clears_platform_state_then_invokes_fixture(self):
        driver = self.driver()
        events = []
        driver.device.app_clear.side_effect = lambda package: events.append(('clear', package))
        driver.application.reset.side_effect = lambda device, adb: events.append(('fixture', device))

        def adb(*args):
            return "Result: Parcel( 00000000 '....')" if args[:3] == ('shell', 'service', 'call') else ''

        with (
            patch.object(mobile_driver, 'safe_device'),
            patch.object(mobile_driver, 'adb', side_effect=adb),
            patch.object(mobile_driver, 'wait_focused_package'),
        ):
            driver.reset()
        self.assertEqual(events[0], ('clear', driver.package))
        self.assertEqual(events[1], ('fixture', driver.device))
        driver.settle.assert_called_once()

    def test_private_checker_is_generic_and_requires_boolean(self):
        driver = self.driver()
        driver.application.check = Mock(return_value=True)
        self.assertIs(driver.call('check_fixture', {}), True)
        driver.application.check.return_value = 'PASS'
        with self.assertRaises(ValueError):
            driver.call('check_fixture', {})
        del driver.application.check
        with self.assertRaises(ValueError):
            driver.call('check_fixture', {})
        from gui_agent_bench.broker import validate_call

        with self.assertRaises(ValueError):
            validate_call('step', {'action': 'check_fixture'})

    def test_ui_names_use_same_rules_for_every_declared_package(self):
        template = '<hierarchy><node package="{package}" class="android.widget.EditText" hint="Hint" text="Value" resource-id="editor" bounds="[0,128][720,900]" enabled="true"/></hierarchy>'
        for package in ('org.example.reader', 'net.gsantner.markor'):
            self.assertEqual(
                mobile_driver.nodes_from_xml(template.format(package=package), package)[0]['name'], 'editor'
            )


class ExampleTaskBehavior(unittest.TestCase):
    def test_only_task_fixture_applies_the_restart_fault(self):
        Application = task_module().Application
        for faulty in (False, True):
            settings = json.loads(
                (TASK / 'variants' / ('faulty' if faulty else 'correct') / 'settings.json').read_text()
            )
            fixture = Application(settings)
            fixture.launch = Mock()
            device, adb = Mock(), Mock()
            fixture.reload(device, adb)
            self.assertEqual(device.method_calls[0].args, ('back',))
            self.assertEqual(device.method_calls[1].args, ('back',))
            device.app_stop.assert_called_once()
            if faulty:
                self.assertEqual(device.push.call_args.args[0].getvalue(), b'')
            else:
                device.push.assert_not_called()
            fixture.launch.assert_called_once_with(device, adb)


class PlatformHasNoApplicationDependency(unittest.TestCase):
    def test_runtime_verification_never_reads_an_apk_or_queries_a_package(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'runtime/android').mkdir(parents=True)
        for name in ('lock-linux-x86_64.json', 'requirements.txt'):
            shutil.copy2(ROOT / 'runtime/android' / name, root / 'runtime/android' / name)
        lock = json.loads((root / 'runtime/android/lock-linux-x86_64.json').read_text())
        sdk, assets = Path('/test-sdk'), Path('/test-u2/assets')

        def sha(path):
            path = Path(path)
            if path.is_relative_to(sdk):
                return lock['sdk_sha256'][path.relative_to(sdk).as_posix()]
            if path.is_relative_to(assets):
                return lock['driver_assets_sha256'][path.name]
            return 'd' * 64

        expected = dict(
            line.split('==') for line in (root / 'runtime/android/requirements.txt').read_text().splitlines()
        )

        def adb(*args):
            replies = {
                ('shell', 'getprop', 'ro.build.fingerprint'): lock['build_fingerprint'],
                ('shell', 'wm', 'size'): 'Physical size: 720x1280',
                ('shell', 'wm', 'density'): 'Physical density: 240',
                ('shell', 'getprop', 'persist.sys.locale'): 'en-US',
            }
            return replies[args]

        with (
            patch.object(mobile_runtime, 'sha_file', side_effect=sha),
            patch.object(mobile_driver, 'sdk_path', return_value=sdk),
            patch.object(mobile_driver, 'adb', side_effect=adb),
            patch.dict(sys.modules, {'uiautomator2': types.SimpleNamespace(__file__='/test-u2/__init__.py')}),
            patch.object(mobile_runtime.importlib.metadata, 'version', side_effect=expected.__getitem__),
            patch.object(mobile_runtime.sys, 'version', '3.11.9 test'),
        ):
            result = mobile_runtime.verify_runtime(root)
        self.assertEqual(result['schema'], 'android-platform-v1')
        self.assertNotIn('apk_sha256', result)
        self.assertNotIn('task_application', result)


if __name__ == '__main__':
    unittest.main()
