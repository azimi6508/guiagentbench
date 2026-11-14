"""Remote applications own their assets; the controller records their boundary."""

from gui_agent_bench.io import dump, regular_file, strict_json
from gui_agent_bench.task_package import metadata, IDENTIFIER
from gui_agent_bench.tv_import import verify_task

VERSION = 'remote-application-v1'


def app_mounts(task, platform):
    if platform == 'tv':
        verify_task(task)
    return []


def record_app(task, folder, app, network):
    verify_task(task)
    values = metadata(task)['metadata']
    from gui_agent_bench.task_runtime import runtime

    config = runtime(task)
    dump(
        folder / 'tv-runtime.json',
        {
            'schema': VERSION,
            'task': values.get('domain', values['platform']) + '/' + values['task_id'],
            'profile': config['environment_profile'],
            'transport': 'remote-call',
        },
    )
    return audit_app(folder)


def audit_app(folder):
    from gui_agent_bench.applications import audit_app as audit_application

    result = audit_application(folder)
    record = strict_json(regular_file(folder / 'tv-runtime.json', folder))
    if (
        set(record) != {'schema', 'task', 'profile', 'transport'}
        or record['schema'] != VERSION
        or not isinstance(record['task'], str)
        or not IDENTIFIER.fullmatch(record['task'])
        or record['profile'] not in {'generic', 'tv'}
        or record['transport'] != 'remote-call'
    ):
        raise ValueError('Remote application contract differs')
    return result
