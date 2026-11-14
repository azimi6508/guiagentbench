"""Host portability for the trusted, dedicated Android runtime."""

from contextlib import contextmanager
import os
from pathlib import Path
import platform
import sys


ROOT = Path(__file__).resolve().parents[2]
LOCKS = {'windows-x86_64': 'lock.json', 'linux-x86_64': 'lock-linux-x86_64.json'}


def host_platform():
    machine = platform.machine().lower()
    if machine not in {'amd64', 'x86_64'}:
        raise ValueError('native runtime requires an x86_64 host')
    if sys.platform == 'win32':
        return 'windows-x86_64'
    if sys.platform == 'linux':
        return 'linux-x86_64'
    raise ValueError('native host platform is unsupported')


def runtime_lock(root, identity=None):
    identity = host_platform() if identity is None else identity
    if identity not in LOCKS:
        raise ValueError('unregistered native host contract')
    return root / 'runtime/android' / LOCKS[identity]


def sdk_path(root=ROOT):
    # Only the trusted controller chooses the SDK. Clients cannot supply paths.
    for name in ('ANDROID_SDK_ROOT', 'ANDROID_HOME'):
        if os.environ.get(name):
            return Path(os.environ[name]).expanduser().resolve()
    if host_platform() == 'windows-x86_64':
        return Path(os.environ['LOCALAPPDATA']) / 'Android/Sdk'
    return root / '.mobile/sdk'


def sdk_tool(name, root=ROOT):
    relative = {
        'adb': 'platform-tools/adb',
        'emulator': 'emulator/emulator',
        'avdmanager': 'cmdline-tools/latest/bin/avdmanager',
        'sdkmanager': 'cmdline-tools/latest/bin/sdkmanager',
    }[name]
    suffix = ('.bat' if name.endswith('manager') else '.exe') if os.name == 'nt' else ''
    return sdk_path(root) / (relative + suffix)


def native_python(root):
    return root / '.mobile/venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def project_adb_keys(root):
    """The dedicated research AVD uses its project-local host ADB key.

    Pass only fixed project-local paths to the trusted server, never inherited
    keys or key contents. No device reconnect or server restart occurs here.
    """
    root = root.resolve()
    keys = []
    for name in ('.mobile',):
        path = root / name / 'home/.android/adbkey'
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.resolve() != path)):
            raise ValueError('Research ADB key must be a regular file inside its project home')
        if path.is_file():
            keys.append(str(path))
    return os.pathsep.join(keys)


def native_environment(root):
    # No provider credentials, Python hooks, ADB overrides or personal Android
    # configuration are inherited by the driver/emulator.
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'LOCALAPPDATA'}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    cache = root / '.mobile'
    sdk = sdk_path(root)
    env.update(
        HOME=str(cache / 'home'),
        ANDROID_USER_HOME=str(cache / 'android-user'),
        ANDROID_AVD_HOME=str(cache / 'avd'),
        ANDROID_HOME=str(sdk),
        ANDROID_SDK_ROOT=str(sdk),
        PATH=str(sdk / 'platform-tools') + os.pathsep + env.get('PATH', ''),
        LANG='C.UTF-8',
    )
    keys = project_adb_keys(root)
    if keys:
        env['ADB_VENDOR_KEYS'] = keys
    return env


@contextmanager
def device_lock(root):
    """Fail immediately on contention; the OS releases the lock on crashes."""
    with (root / '.mobile/device.lock').open('a+b') as lock:
        lock.seek(0)
        lock.write(b'0')
        lock.flush()
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt

            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
