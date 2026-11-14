"""Audit the platform, task-owned fixture binding and transport-only relay."""

import json
from pathlib import Path
import re
from gui_agent_bench.io import regular_file, digest
from gui_agent_bench.mobile_host import runtime_lock
from gui_agent_bench.mobile_runtime import VERSION as PLATFORM_VERSION
from gui_agent_bench.native_application import VERSION as FIXTURE_VERSION
from gui_agent_bench.task_package import IDENTIFIER


def audit_mobile(folder, root=None):
    root = root or Path(__file__).resolve().parents[2]
    read = lambda name: json.loads(regular_file(folder / name, folder))
    runtime, app, network = (read('mobile-runtime.json'), read('app-container.json'), read('mobile-app-network.json'))
    identity = runtime['host_platform']
    lock_data = regular_file(runtime_lock(root, identity), root)
    lock = json.loads(lock_data)
    if (
        runtime.get('schema') != PLATFORM_VERSION
        or runtime['status'] != 'verified'
        or runtime['lock_sha256'] != digest(lock_data)
        or runtime['sdk_sha256'] != lock['sdk_sha256']
        or runtime['driver_assets_sha256'] != lock['driver_assets_sha256']
        or runtime['build_fingerprint'] != lock['build_fingerprint']
        or runtime['python_version'] != lock['python_version']
        or runtime['avd'] != 'GuiAgentBench'
        or runtime['serial'] != 'emulator-5580'
        or runtime['viewport'] != [720, 1280]
        or runtime['locale'] != 'en-US'
    ):
        raise ValueError('Native platform differs from its declared lock')
    dependencies = dict(
        line.split('==') for line in (root / 'runtime/android/requirements.txt').read_text().splitlines()
    )
    if runtime['dependencies'] != dependencies:
        raise ValueError('Native dependency record differs')
    declaration = read('native-application.json')
    if (
        set(declaration) != {'schema', 'task', 'package', 'apk_sha256', 'source_sha256', 'settings_sha256'}
        or declaration['schema'] != FIXTURE_VERSION
        or not IDENTIFIER.fullmatch(declaration['task'])
        or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+', declaration['package'])
        or any(
            not re.fullmatch(r'[a-f0-9]{64}', declaration[field])
            for field in ('apk_sha256', 'source_sha256', 'settings_sha256')
        )
        or runtime.get('task_application') != declaration
    ):
        raise ValueError('Native fixture or application differs from the staged task binding')
    host = app['HostConfig']
    if (
        host['PortBindings']
        or app['NetworkSettings']['Ports']
        or set(app['NetworkSettings']['Networks']) != {network['Name']}
        or not network['Internal']
        or not host['ReadonlyRootfs']
        or host['Privileged']
        or host.get('Devices')
        or host.get('CapAdd')
        or set(host['CapDrop'] or []) != {'ALL'}
        or 'no-new-privileges' not in host['SecurityOpt']
        or app['Config']['User'] != 'pwuser'
        or app['Config']['Entrypoint'] != ['python', '-m', 'gui_agent_bench.mobile_relay']
        or not app['Config']['OpenStdin']
    ):
        raise ValueError('Native relay boundary differs')
    if any(m['Type'] != 'tmpfs' for m in app['Mounts']):
        raise ValueError('Native relay must not mount task files or settings')
    if any(
        any(word in entry.split('=', 1)[0].upper() for word in ('KEY', 'TOKEN', 'RENDEZVOUS'))
        for entry in app['Config']['Env']
    ):
        raise ValueError('Native relay must receive its secret only on stdin')
    return {
        'native_runtime_verified': True,
        'adb_exposed_to_agent': False,
        'rendezvous_transport': 'docker-exec-stdio',
        'published_ports': [],
        'task_files_in_relay': False,
        'apk_sha256': declaration['apk_sha256'],
        'apk_package': declaration['package'],
        'fixture_source_sha256': declaration['source_sha256'],
        'settings_sha256': declaration['settings_sha256'],
    }
