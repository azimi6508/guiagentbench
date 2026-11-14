"""Host portability must preserve native identity, locking and secret isolation."""

import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from gui_agent_bench.mobile_host import (
    device_lock,
    host_platform,
    native_environment,
    project_adb_keys,
    runtime_lock,
    sdk_path,
    sdk_tool,
)
from gui_agent_bench.mobile_driver import adb, safe_device


class NativeHostTests(unittest.TestCase):
    def test_platform_locks_are_registered_and_unknown_hosts_fail_closed(self):
        for system, machine, expected in [
            ('linux', 'x86_64', 'lock-linux-x86_64.json'),
            ('win32', 'AMD64', 'lock.json'),
        ]:
            with patch('sys.platform', system), patch('platform.machine', return_value=machine):
                self.assertEqual(runtime_lock(ROOT).name, expected)
        for system, machine in [('darwin', 'x86_64'), ('linux', 'aarch64')]:
            with patch('sys.platform', system), patch('platform.machine', return_value=machine):
                with self.assertRaises(ValueError):
                    host_platform()
        with self.assertRaises(ValueError):
            runtime_lock(ROOT, '../../untrusted')
        # A historical Windows record is audited against its own lock on Linux.
        self.assertEqual(runtime_lock(ROOT, 'windows-x86_64').name, 'lock.json')

    def test_linux_sdk_override_and_checkout_default(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch('sys.platform', 'linux'),
            patch('platform.machine', return_value='x86_64'),
        ):
            self.assertEqual(sdk_path(ROOT), ROOT / '.mobile/sdk')
            self.assertEqual(sdk_tool('adb', ROOT), ROOT / '.mobile/sdk/platform-tools/adb')
            with patch.dict(os.environ, {'ANDROID_HOME': '/sdk-one', 'ANDROID_SDK_ROOT': '/sdk-two'}):
                self.assertEqual(sdk_path(ROOT), Path('/sdk-two'))

    def test_native_environment_uses_isolated_homes_without_secrets_or_adb_overrides(self):
        inherited = {
            'PATH': '/usr/bin',
            'HOME': '/personal',
            'OPENROUTER_API_KEY': 'secret',
            'PYTHONPATH': '/hooks',
            'ADB_SERVER_SOCKET': 'tcp:remote:5037',
            'ANDROID_USER_HOME': '/personal-android',
        }
        with patch.dict(os.environ, inherited, clear=True):
            env = native_environment(ROOT)
        self.assertEqual(env['HOME'], str(ROOT / '.mobile/home'))
        self.assertEqual(env['ANDROID_AVD_HOME'], str(ROOT / '.mobile/avd'))
        self.assertEqual(env['ANDROID_USER_HOME'], str(ROOT / '.mobile/android-user'))
        for name in ('OPENROUTER_API_KEY', 'PYTHONPATH', 'ADB_SERVER_SOCKET'):
            self.assertNotIn(name, env)

    def test_historical_windows_runtime_audits_on_linux_without_relabeling(self):
        from gui_agent_bench.mobile_audit import audit_mobile
        from gui_agent_bench.mobile_runtime import VERSION, sha_file

        lock_path = runtime_lock(ROOT, 'windows-x86_64')
        lock = json.loads(lock_path.read_text())
        runtime = {k: lock[k] for k in ('sdk_sha256', 'driver_assets_sha256', 'build_fingerprint', 'python_version')}
        runtime.update(
            schema=VERSION,
            host_platform='windows-x86_64',
            locale='en-US',
            status='verified',
            lock_sha256=sha_file(lock_path),
            avd='GuiAgentBench',
            serial='emulator-5580',
            viewport=[720, 1280],
            dependencies=dict(
                line.split('==') for line in (ROOT / 'runtime/android/requirements.txt').read_text().splitlines()
            ),
        )
        app = {
            'HostConfig': {
                'PortBindings': {},
                'ReadonlyRootfs': True,
                'Privileged': False,
                'Devices': [],
                'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges'],
            },
            'NetworkSettings': {'Ports': {}, 'Networks': {'internal-app': {}}},
            'Config': {
                'User': 'pwuser',
                'Entrypoint': ['python', '-m', 'gui_agent_bench.mobile_relay'],
                'OpenStdin': True,
                'Env': ['PATH=/usr/bin'],
            },
            'Mounts': [],
        }
        declaration = {
            'schema': 'native-fixture-v1',
            'task': 'mobile/example',
            'package': 'org.example.app',
            'apk_sha256': 'a' * 64,
            'source_sha256': 'b' * 64,
            'settings_sha256': 'c' * 64,
        }
        runtime['task_application'] = declaration
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for name, data in [
                ('native-application.json', declaration),
                ('mobile-runtime.json', runtime),
                ('app-container.json', app),
                ('mobile-app-network.json', {'Name': 'internal-app', 'Internal': True}),
            ]:
                (folder / name).write_text(json.dumps(data))
            self.assertTrue(audit_mobile(folder, ROOT)['native_runtime_verified'])
            runtime['host_platform'] = 'linux-x86_64'
            (folder / 'mobile-runtime.json').write_text(json.dumps(runtime))
            with self.assertRaises(ValueError):
                audit_mobile(folder, ROOT)

    def test_native_home_uses_only_fixed_project_adb_key(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(os.environ, {'ADB_VENDOR_KEYS': '/personal/key'}, clear=True),
        ):
            root = Path(temp).resolve()
            self.assertEqual(project_adb_keys(root), '')
            self.assertNotIn('ADB_VENDOR_KEYS', native_environment(root))
            key = root / '.mobile/home/.android/adbkey'
            key.parent.mkdir(parents=True)
            key.write_text('synthetic test key; never loaded by ADB')
            self.assertEqual(native_environment(root)['ADB_VENDOR_KEYS'], str(key))
            other = root / 'other'
            other.write_text('not admitted')
            key.unlink()
            key.symlink_to(other)
            with self.assertRaisesRegex(ValueError, 'Research ADB key'):
                project_adb_keys(root)

    def test_adb_explicitly_targets_research_serial_and_strips_credentials(self):
        with (
            patch.dict(os.environ, {'OPENROUTER_API_KEY': 'secret'}),
            patch('gui_agent_bench.mobile_driver.subprocess.run') as run,
        ):
            run.return_value.stdout = b'ok\n'
            self.assertEqual(adb('shell', 'getprop'), 'ok')
        args, kwargs = run.call_args
        self.assertEqual(args[0][1:], ['-s', 'emulator-5580', 'shell', 'getprop'])
        self.assertNotIn('OPENROUTER_API_KEY', kwargs['env'])

    def test_wrong_avd_is_rejected_before_guest_operations(self):
        with patch('gui_agent_bench.mobile_driver.adb', return_value='PersonalAVD\nOK') as call:
            with self.assertRaises(RuntimeError):
                safe_device()
            call.assert_called_once_with('emu', 'avd', 'name')

    def test_sdk_extraction_rejects_escape_paths_and_symlinks(self):
        spec = importlib.util.spec_from_file_location('mobile_sdk', ROOT / 'scripts/mobile_sdk.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index, path in enumerate(('../outside', 'emulator/../../outside', '/emulator/outside', 'wrong/file')):
                archive = root / (str(index) + '.zip')
                with zipfile.ZipFile(archive, 'w') as bundle:
                    bundle.writestr(path, 'escape')
                with self.assertRaises(ValueError):
                    installer.extract(archive, root / 'target', 'emulator')
            archive = root / 'link.zip'
            info = zipfile.ZipInfo('emulator/link')
            info.external_attr = 0o120777 << 16
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr(info, '/outside')
            with self.assertRaises(ValueError):
                installer.extract(archive, root / 'target', 'emulator')
            self.assertFalse((root / 'target').exists())

    def setup_module(self):
        spec = importlib.util.spec_from_file_location('mobile_setup', ROOT / 'scripts/mobile_setup.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_shutdown_waits_for_adb_and_launcher_exit(self):
        module = self.setup_module()
        with (
            patch.object(module, 'emulator_present', side_effect=[True, False, False]) as present,
            patch.object(module, 'owned_emulator_running', side_effect=[True, False]) as running,
            patch('time.monotonic', side_effect=[0, 1, 2]),
            patch('time.sleep') as sleep,
        ):
            module.wait_for_shutdown(ROOT / '.mobile', {})
        self.assertEqual(present.call_count, 3)
        self.assertEqual(running.call_count, 2)
        self.assertEqual(sleep.call_count, 2)

    def test_shutdown_timeout_cannot_report_success(self):
        module = self.setup_module()
        with patch.object(module, 'emulator_present', return_value=True), patch('time.monotonic', side_effect=[0, 46]):
            with self.assertRaises(TimeoutError):
                module.wait_for_shutdown(ROOT / '.mobile', {})

    def test_device_inventory_matches_exact_research_serial_even_when_offline(self):
        module = self.setup_module()
        with (
            patch.object(module, 'sdk_tool', return_value=Path('adb')),
            patch.object(module.subprocess, 'check_output') as command,
        ):
            command.return_value = 'List of devices attached\nemulator-5580\toffline\n'
            self.assertTrue(module.emulator_present({}))
            command.return_value = 'List of devices attached\nemulator-55800\tdevice\n'
            self.assertFalse(module.emulator_present({}))

    def test_cold_boot_refuses_other_emulators_including_offline(self):
        module = self.setup_module()
        with (
            patch.object(module, 'sdk_tool', return_value=Path('adb')),
            patch.object(module.subprocess, 'check_output') as command,
        ):
            for state in ('device', 'offline'):
                command.return_value = 'List of devices attached\nemulator-5582\t' + state + '\n'
                with self.subTest(state=state), self.assertRaisesRegex(RuntimeError, 'before other emulators'):
                    module.require_unambiguous_emulator_start({})

    def test_cold_boot_inventory_does_not_select_a_physical_device(self):
        module = self.setup_module()
        with (
            patch.object(module, 'sdk_tool', return_value=Path('adb')),
            patch.object(module.subprocess, 'check_output') as command,
        ):
            for inventory in ('List of devices attached\n', 'List of devices attached\nphysical-serial\tdevice\n'):
                command.return_value = inventory
                module.require_unambiguous_emulator_start({})

    def test_display_geometry_rejects_unapplied_hardware_cutout(self):
        module = self.setup_module()
        hardware = 'DisplayDeviceInfo{"Built-in Screen": cutout DisplayCutout{insets=Rect(0, 128 - 0, 0)'
        active = 'mDisplayCutout=DisplayCutout{insets=Rect(0, 0 - 0, 0)'
        with patch.object(module, 'adb', side_effect=[hardware, active]):
            with self.assertRaisesRegex(RuntimeError, 'cutout differs'):
                module.verify_display_geometry()

    def test_display_geometry_requires_unambiguous_matching_insets(self):
        module = self.setup_module()
        hardware = 'DisplayDeviceInfo{"Built-in Screen": cutout DisplayCutout{insets=Rect(0, 128 - 0, 0)'
        active = 'mDisplayCutout=DisplayCutout{insets=Rect(0, 128 - 0, 0)'
        with patch.object(module, 'adb', side_effect=[hardware, active]):
            module.verify_display_geometry()
        with patch.object(module, 'adb', side_effect=[hardware, active + '\n' + active]):
            with self.assertRaises(RuntimeError):
                module.verify_display_geometry()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux flock integration')
    def test_device_lock_contends_across_processes_and_releases_after_crash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.mobile').mkdir()
            code = (
                'import sys; from pathlib import Path; '
                'from gui_agent_bench.mobile_host import device_lock; '
                'ctx=device_lock(Path(sys.argv[1])); ctx.__enter__(); '
                'print("locked", flush=True); sys.stdin.read()'
            )
            env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
            owner = subprocess.Popen(
                [sys.executable, '-c', code, str(root)],
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(owner.stdout.readline().strip(), 'locked')
                with self.assertRaises(BlockingIOError):
                    with device_lock(root):
                        pass
                owner.kill()
                owner.wait(timeout=5)
                with device_lock(root):
                    pass
            finally:
                if owner.poll() is None:
                    owner.kill()
                    owner.wait(timeout=5)
                owner.stdin.close()
                owner.stdout.close()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux process-group integration')
    def test_session_cleanup_kills_descendants_even_after_parent_exits(self):
        from gui_agent_bench.mobile_session import MobileSession

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.mobile').mkdir()
            child = (
                'import signal,sys,time; from pathlib import Path; '
                'from gui_agent_bench.mobile_host import device_lock; '
                'signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                'ctx=device_lock(Path(sys.argv[1]));ctx.__enter__(); '
                'print("child locked",flush=True);time.sleep(60)'
            )
            parent = (
                'import subprocess,sys; '
                'subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]]); '
                'sys.stdin.read()'
            )
            env = {'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(ROOT / 'src')}
            owner = subprocess.Popen(
                [sys.executable, '-c', parent, child, str(root)],
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            session = object.__new__(MobileSession)
            session.processes, session.streams = [owner], []
            try:
                self.assertEqual(owner.stdout.readline().strip(), 'child locked')
                owner.terminate()
                owner.wait(timeout=5)
                with self.assertRaises(BlockingIOError):
                    with device_lock(root):
                        pass
                session.close()
                deadline = time.monotonic() + 5
                while True:
                    try:
                        with device_lock(root):
                            break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(0.02)
            finally:
                session.close()
                owner.stdin.close()
                owner.stdout.close()


if __name__ == '__main__':
    unittest.main()
