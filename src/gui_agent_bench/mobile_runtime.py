"""Verify immutable native runtime inputs against the platform lock."""

import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path
from gui_agent_bench.mobile_host import host_platform, runtime_lock


VERSION = 'android-platform-v1'


def sha_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_runtime(root):
    from gui_agent_bench.mobile_driver import sdk_path, adb

    identity = host_platform()
    lock_path = runtime_lock(root, identity)
    lock = json.loads(lock_path.read_text())
    if sys.version.split()[0] != lock['python_version']:
        raise ValueError('native Python runtime differs')
    sdk = sdk_path()
    for relative, expected in lock['sdk_sha256'].items():
        if sha_file(sdk / relative) != expected:
            raise ValueError('native SDK lock mismatch: ' + relative)
    import uiautomator2

    assets = Path(uiautomator2.__file__).parent / 'assets'
    for name, expected in lock['driver_assets_sha256'].items():
        if sha_file(assets / name) != expected:
            raise ValueError('native helper asset differs')
    versions = {}
    for line in (root / 'runtime/android/requirements.txt').read_text().splitlines():
        name, expected = line.split('==')
        versions[name] = importlib.metadata.version(name)
        if versions[name] != expected:
            raise ValueError('native Python dependency differs: ' + name)
    if adb('shell', 'getprop', 'ro.build.fingerprint') != lock['build_fingerprint']:
        raise ValueError('booted system image differs')
    if '720x1280' not in adb('shell', 'wm', 'size') or '240' not in adb('shell', 'wm', 'density'):
        raise ValueError('native viewport differs')
    locale = adb('shell', 'getprop', 'persist.sys.locale') or adb('shell', 'getprop', 'ro.product.locale')
    if locale != 'en-US':
        raise ValueError('native locale differs')
    return {
        'schema': VERSION,
        'host_platform': identity,
        'lock_sha256': sha_file(lock_path),
        'sdk_sha256': lock['sdk_sha256'],
        'build_fingerprint': lock['build_fingerprint'],
        'dependencies': versions,
        'driver_assets_sha256': lock['driver_assets_sha256'],
        'python_version': lock['python_version'],
        'serial': 'emulator-5580',
        'avd': 'GuiAgentBench',
        'locale': locale,
        'driver_source_sha256': sha_file(Path(__file__).with_name('mobile_driver.py')),
        'viewport': [720, 1280],
        'driver': 'uiautomator2',
        'status': 'verified',
    }
