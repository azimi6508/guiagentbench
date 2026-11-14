"""Task-owned Android fixtures and app provenance, separate from the platform."""

from pathlib import Path
import re
import subprocess
import importlib.util
import sys
import uuid
import urllib.request

from gui_agent_bench.io import digest, strict_json, regular_file
from gui_agent_bench.task_package import task_path, integration, local_file, verify

VERSION = 'native-fixture-v1'
MAX_APK_BYTES = 256_000_000


def declared_application(root, identifier, variant=None):
    task = task_path(root, identifier)
    spec = integration(task)
    if not spec.get('native_application'):
        raise ValueError('Mobile tasks must declare their task-owned application fixture')
    record = {
        'schema': VERSION,
        'task': identifier,
        'package': spec['native_package'],
        'apk_sha256': spec['native_apk_sha256'],
        'source_sha256': digest(local_file(task, spec['native_application'], 65_536)),
    }
    if variant is not None:
        if variant not in {'correct', 'faulty'}:
            raise ValueError('Unknown native variant')
        record['settings_sha256'] = digest(local_file(task, 'variants/' + variant + '/settings.json'))
    return record


def verify_installed(root, identifier):
    from gui_agent_bench.mobile_driver import safe_device, adb

    safe_device()
    record = declared_application(root, identifier)
    try:
        output = adb('shell', 'pm', 'path', record['package'])
    except subprocess.CalledProcessError:
        raise ValueError('The declared application is unavailable; install its pinned APK') from None
    # Pin one complete APK, including platform-provided apps. Split packages
    # need a separately defined complete artifact contract before admission.
    path = output.removeprefix('package:')
    if (
        not output.startswith('package:')
        or not re.fullmatch(
            r'/(?:data/app|system/(?:app|priv-app)|system_ext/(?:app|priv-app)|product/(?:app|priv-app))/[A-Za-z0-9_./+=~-]+\.apk',
            path,
        )
        or '..' in path.split('/')
    ):
        raise ValueError('The declared app must resolve to one pinned installed APK')
    checksum = adb('shell', 'sha256sum', path).split()
    if not checksum or checksum[0] != record['apk_sha256']:
        raise ValueError('Installed task application differs from its APK pin')
    return record


def load_fixture(root, identifier, variant):
    """Load reviewed task source only after package and installed-app checks.

    This is trusted environment code, never a generated submission. Discovery
    and validation do not import it. Configuration remains opaque to the driver.
    """
    task = task_path(root, identifier)
    verify(task)
    declaration = declared_application(root, identifier, variant)
    record = verify_installed(root, identifier)
    if record != {key: value for key, value in declaration.items() if key != 'settings_sha256'}:
        raise ValueError('Native application declaration changed during verification')
    source = integration(task)['native_application']
    data = local_file(task, source, 65_536)
    settings_data = local_file(task, 'variants/' + variant + '/settings.json')
    if (
        digest(data) != record['source_sha256']
        or digest(data) != declaration['source_sha256']
        or digest(settings_data) != declaration['settings_sha256']
    ):
        raise ValueError('Native fixture inputs changed while loading')
    # Register an isolated real module so normal Python features such as
    # dataclasses and postponed annotations work. Execute the verified bytes,
    # rather than rereading source or accepting a cached task bytecode file.
    name = '_gui_native_fixture_' + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, task / source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        exec(compile(data, module.__file__, 'exec'), module.__dict__)
        application = module.Application(strict_json(settings_data))
        if any(not callable(getattr(application, method, None)) for method in ('reset', 'launch', 'reload')):
            raise ValueError('Native Application must implement reset, launch and reload')
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return application, declaration


def install_apk(root, identifier, source=None):
    """Explicit operator setup, using only this task's declared APK pin."""
    from gui_agent_bench.mobile_driver import safe_device, adb

    task = task_path(root, identifier)
    spec = integration(task)
    record = declared_application(root, identifier)
    if source is None:
        url = spec.get('native_apk_url')
        if not url:
            raise ValueError('Supply --apk or declare native_apk_url in the task')
        cache = root / '.mobile/apps'
        cache.mkdir(parents=True, exist_ok=True)
        source = cache / (record['apk_sha256'] + '.apk')
        if not source.exists():
            temporary = source.with_suffix('.part')
            try:
                with urllib.request.urlopen(url, timeout=60) as response, temporary.open('xb') as output:
                    size = 0
                    while chunk := response.read(1_000_000):
                        size += len(chunk)
                        if size > MAX_APK_BYTES:
                            raise ValueError('APK exceeds the explicit file budget')
                        output.write(chunk)
                if digest(regular_file(temporary, cache, MAX_APK_BYTES)) != record['apk_sha256']:
                    raise ValueError('Downloaded APK differs from the task pin')
                temporary.replace(source)
            finally:
                if temporary.exists():
                    temporary.unlink()
    source = Path(source).absolute()
    if digest(regular_file(source, source.parent, MAX_APK_BYTES)) != record['apk_sha256']:
        raise ValueError('APK file differs from the task pin')
    safe_device()
    adb('install', '-r', str(source), timeout=90)
    return verify_installed(root, identifier)
