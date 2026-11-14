"""Generic application-container evidence and isolation checks."""

import json
from gui_agent_bench.io import dump, regular_file


def record_app(task, folder, app, network):
    from gui_agent_bench.task_runtime import runtime

    if runtime(task)['platform'] not in {'web', 'tv'}:
        return
    from gui_agent_bench.docker import docker

    dump(folder / 'app-network.json', json.loads(docker('network', 'inspect', network))[0])
    dump(folder / 'app-isolation.json', audit_app(folder))


def audit_app(folder):
    app = json.loads(regular_file(folder / 'app-container.json', folder))
    network = json.loads(regular_file(folder / 'app-network.json', folder))
    host = app['HostConfig']
    binds = [m for m in app['Mounts'] if m['Type'] != 'tmpfs']
    from gui_agent_bench.task_runtime import WRITABLE_ROOT_LABEL

    key, value = WRITABLE_ROOT_LABEL.split('=')
    writable = (app['Config'].get('Labels') or {}).get(key) == value
    if (
        host['ReadonlyRootfs'] == writable
        or host['Privileged']
        or host.get('CapAdd')
        or host.get('Devices')
        or set(host.get('CapDrop') or []) != {'ALL'}
        or 'no-new-privileges' not in host['SecurityOpt']
        or host.get('PortBindings')
        or any(app['NetworkSettings']['Ports'].values())
        or host.get('PidMode') == 'host'
        or host.get('IpcMode') == 'host'
        or not network['Internal']
        or set(app['NetworkSettings']['Networks']) != {network['Name']}
        or app['Config'].get('User') in {'', '0', 'root', '0:0'}
        or len(binds) != 1
        or binds[0]['Destination'] != '/settings.json'
        or binds[0]['RW']
    ):
        raise ValueError('Application container boundary differs')
    return {
        'status': 'pass',
        'read_only_root': not writable,
        'internal_network_only': True,
        'published_ports': [],
        **({'writable_root': 'task-declared disposable container layer'} if writable else {}),
    }


def app_mounts(task, variant, platform):
    """Only web/TV applications consume settings inside their container.

    Native configuration goes exclusively to the trusted host fixture. Its
    transport-only relay has no task files or variant settings mounted.
    """
    if platform == 'mobile':
        return []
    from gui_agent_bench.docker import mount
    from gui_agent_bench.tv_session import app_mounts as asset_mounts

    return [*asset_mounts(task, platform), *mount(task / 'variants' / variant / 'settings.json', '/settings.json')]
