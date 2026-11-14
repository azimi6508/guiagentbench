"""Prepare/start/stop the dedicated, platform-pinned research emulator.

Uses the already installed licensed SDK image. Does not accept SDK licenses,
modify virtualization settings, use a personal AVD or address physical devices.
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from gui_agent_bench.mobile_driver import sdk_path, adb, safe_device, AVD
from gui_agent_bench.mobile_runtime import sha_file
from gui_agent_bench.mobile_host import (
    host_platform,
    runtime_lock,
    sdk_tool,
    native_python,
    native_environment,
    device_lock,
)


def emulator_present(env):
    devices = subprocess.check_output([str(sdk_tool('adb')), 'devices'], text=True, env=env, timeout=10)
    return any(line.split()[0] == 'emulator-5580' for line in devices.splitlines()[1:] if line.strip())


def require_unambiguous_emulator_start(env):
    # The SDK's own startup broadcasts use adb -e, even though our driver
    # always selects an exact serial. A second emulator can leave the Pixel 6
    # display cutout unapplied and shift every app's layout after cold boot.
    devices = subprocess.check_output([str(sdk_tool('adb')), 'devices'], text=True, env=env, timeout=10)
    if any(line.split()[0].startswith('emulator-') for line in devices.splitlines()[1:] if line.strip()):
        raise RuntimeError('Start GuiAgentBench before other emulators; SDK initialization uses adb -e')


def verify_display_geometry():
    # Compare the configured hardware inset with WindowManager, not an app
    # screenshot or a learned visual baseline. Fail before any task starts.
    pattern = r'DisplayCutout\{insets=Rect\((\d+), (\d+) - (\d+), (\d+)\)'
    devices = adb('shell', 'dumpsys', 'display')
    windows = adb('shell', 'dumpsys', 'window', 'displays')
    hardware = re.findall(r'DisplayDeviceInfo\{"Built-in Screen"[^\n]*?cutout ' + pattern, devices)
    active = re.findall(r'mDisplayCutout=' + pattern, windows)
    if len(hardware) != 1 or len(active) != 1 or hardware[0] != active[0]:
        raise RuntimeError(
            'Research display cutout differs from the configured device; stop research AVDs and start GuiAgentBench first'
        )


def wait_display_geometry(timeout=30):
    """Allow Android's initial display configuration to settle before any trial."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            verify_display_geometry()
            return
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)


def owned_emulator_running(cache):
    # ADB can disconnect before Linux QEMU releases its AVD locks. The recorded
    # launcher PID is read-only evidence; never signal a PID from this file.
    if os.name == 'nt' or not (cache / 'emulator.pid').is_file():
        return False
    pid = int((cache / 'emulator.pid').read_text())
    if pid <= 0:
        raise ValueError('invalid recorded emulator PID')
    process = Path('/proc') / str(pid)
    try:
        command = (process / 'cmdline').read_bytes().split(b'\0')
        state = (process / 'stat').read_text().rsplit(')', 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return state != 'Z' and any(command[i : i + 2] == [b'-avd', AVD.encode()] for i in range(len(command) - 1))


def wait_for_shutdown(cache, env, timeout=45):
    deadline = time.monotonic() + timeout
    while emulator_present(env) or owned_emulator_running(cache):
        if time.monotonic() >= deadline:
            raise TimeoutError('Research emulator did not finish shutting down')
        time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'start', 'stop', 'check', 'install-app'])
    parser.add_argument('--python', help='pinned interpreter used to create .mobile/venv')
    parser.add_argument('--task', help='Application task for install-app or check')
    parser.add_argument('--apk', type=Path, help='Local APK matching the task pin')
    args = parser.parse_args()
    (ROOT / '.mobile').mkdir(exist_ok=True)
    with device_lock(ROOT):
        setup(args)


def setup(args):
    identity = host_platform()
    cache = ROOT / '.mobile'
    cache.mkdir(exist_ok=True)
    for name in ('home', 'android-user', 'avd'):
        (cache / name).mkdir(exist_ok=True)
    sdk = sdk_path()
    lock = json.loads(runtime_lock(ROOT, identity).read_text())
    env = native_environment(ROOT)
    if args.action == 'stop':
        safe_device()
        adb('emu', 'kill')
        wait_for_shutdown(cache, env)
        print('Stopped dedicated research AVD')
        return
    for relative, sha in lock['sdk_sha256'].items():
        if sha_file(sdk / relative) != sha:
            raise ValueError('Install the pinned SDK before proceeding: ' + relative)
    if identity == 'linux-x86_64' and args.action in {'prepare', 'start'}:
        license_path = sdk / 'licenses/android-sdk-license'
        if not license_path.is_file() or not license_path.read_text().strip():
            raise ValueError('Review and accept SDK terms explicitly with sdkmanager --licenses before setup')
    python = native_python(ROOT)
    if args.action == 'prepare':
        if not python.exists():
            interpreter = args.python or sys.executable
            version = subprocess.check_output(
                [interpreter, '-c', 'import platform; print(platform.python_version())'], text=True
            ).strip()
            if version != lock['python_version']:
                raise ValueError('Use --python with Python ' + lock['python_version'] + ' for the native venv')
            subprocess.run([interpreter, '-m', 'venv', str(cache / 'venv')], check=True)
        version = subprocess.check_output(
            [str(python), '-c', 'import platform; print(platform.python_version())'], text=True
        ).strip()
        if version != lock['python_version']:
            raise ValueError('Existing native venv Python differs from the platform lock')
        subprocess.run(
            [str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'runtime/android/requirements.txt')], check=True
        )
        avd_dir = cache / 'avd'
        avd_dir.mkdir(exist_ok=True)
        if not (avd_dir / (AVD + '.ini')).exists():
            subprocess.run(
                [
                    str(sdk_tool('avdmanager')),
                    'create',
                    'avd',
                    '--name',
                    AVD,
                    '--package',
                    lock['image_package'],
                    '--device',
                    'pixel_6',
                ],
                input='no\n',
                text=True,
                env=env,
                check=True,
            )
            config = avd_dir / (AVD + '.avd/config.ini')
            text = config.read_text()
            import re

            for key, value in {
                'hw.lcd.width': 720,
                'hw.lcd.height': 1280,
                'hw.lcd.density': 240,
                'hw.ramSize': 2048,
                'hw.cpu.ncore': 4,
            }.items():
                pattern = r'^' + re.escape(key) + '=.*$'
                text = (
                    re.sub(pattern, key + '=' + str(value), text, flags=re.M)
                    if re.search(pattern, text, flags=re.M)
                    else text + '\n' + key + '=' + str(value) + '\n'
                )
            config.write_text(text)
        print('Prepared dedicated runtime. Run mobile_setup.py start next.')
        return
    if args.action == 'install-app':
        if not args.task:
            raise ValueError('install-app requires --task')
        env['PYTHONPATH'] = str(ROOT / 'src')
        subprocess.run(
            [
                str(python),
                '-m',
                'gui_agent_bench.preflight',
                '--application-install',
                str(ROOT),
                args.task,
                *([str(args.apk.resolve())] if args.apk is not None else []),
            ],
            cwd=ROOT,
            env=env,
            check=True,
        )
        return
    if args.action == 'start':
        if not (cache / 'avd' / (AVD + '.ini')).is_file():
            raise ValueError('Run mobile_setup.py prepare before starting the research AVD')
        # Do not reuse a process just because it has our serial number.
        if identity == 'linux-x86_64':
            subprocess.run([str(sdk_tool('emulator')), '-accel-check'], env=env, check=True)
        process = None
        if not emulator_present(env):
            require_unambiguous_emulator_start(env)
            with (cache / 'emulator.stdout.log').open('wb') as out, (cache / 'emulator.stderr.log').open('wb') as err:
                options = (
                    {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
                )
                process = subprocess.Popen(
                    [
                        str(sdk_tool('emulator')),
                        '-avd',
                        AVD,
                        '-port',
                        '5580',
                        '-no-window',
                        '-no-snapshot',
                        '-no-audio',
                        '-no-boot-anim',
                        '-gpu',
                        'swiftshader',
                        '-camera-back',
                        'none',
                        '-camera-front',
                        'none',
                    ],
                    env=env,
                    stdout=out,
                    stderr=err,
                    **options,
                )
                (cache / 'emulator.pid').write_text(str(process.pid))
        deadline = time.monotonic() + 300
        while True:
            try:
                safe_device()
                break
            except (OSError, RuntimeError, subprocess.SubprocessError):
                if process is not None and process.poll() is not None:
                    raise RuntimeError('Research emulator exited; see .mobile/emulator logs')
                if time.monotonic() >= deadline:
                    raise TimeoutError('Research AVD did not boot; see .mobile/emulator logs')
                time.sleep(1)
    safe_device()
    if args.action == 'start':
        wait_display_geometry()
    else:
        verify_display_geometry()
    env['PYTHONPATH'] = str(ROOT / 'src')
    subprocess.run(
        [
            str(python),
            '-c',
            'from pathlib import Path; import json; from gui_agent_bench.mobile_runtime import verify_runtime; '
            'print(json.dumps(verify_runtime(Path.cwd()),indent=2))',
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    if args.action == 'check' and args.task:
        subprocess.run(
            [str(python), '-m', 'gui_agent_bench.preflight', '--application-check', str(ROOT), args.task],
            cwd=ROOT,
            env=env,
            check=True,
        )


if __name__ == '__main__':
    main()
