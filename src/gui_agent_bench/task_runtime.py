"""Task-local runtime configuration; evaluated agents never receive it."""

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from gui_agent_bench.task_package import ROOT, discover, metadata, integration

# Compatibility view for callers listing the checkout at import time. Execution
# uses discover(root) on every invocation, so adding a folder needs no source edit.
TASK_IDS = discover(ROOT)


WRITABLE_ROOT_LABEL = 'gui-agent-bench.writable-root=true'


def app_isolation(task, config):
    from gui_agent_bench.docker import isolation

    flags = isolation(memory=f"{config['app_memory_mb']}m")
    if config.get('app_writable_root'):
        # Task-declared: a database-backed app writes into its own disposable
        # container layer. Every other boundary flag is unchanged, and the
        # label lets the application audit tell a declaration from drift.
        flags.remove('--read-only')
        flags += ['--label', WRITABLE_ROOT_LABEL]
    return flags


def runtime(task):
    data = metadata(task)
    platform = data['metadata']['platform']
    defaults = {
        'app_memory_mb': 256,
        'reference_timeout_sec': 60,
        'viewport_width': 1280,
        'viewport_height': 720,
        'timezone': 'UTC',
        'app_writable_root': False,
    }
    specified = data['metadata'].get('runtime', {})
    if not isinstance(specified, dict) or set(specified) - (set(defaults) | {'app_image'}):
        raise ValueError('Unknown app runtime settings')
    values = defaults | specified
    if not isinstance(values.get('app_image'), str) or not re.fullmatch(
        r'[a-z0-9][a-z0-9._/-]*:[a-zA-Z0-9._-]+', values['app_image']
    ):
        raise ValueError('Declare a tagged app_image in metadata.runtime')
    try:
        ZoneInfo(values['timezone'])
    except (TypeError, ValueError, ZoneInfoNotFoundError) as error:
        raise ValueError('Invalid browser timezone') from error
    for key, lower, upper in [
        ('app_memory_mb', 64, 8192),
        ('reference_timeout_sec', 1, 600),
        ('viewport_width', 320, 1920),
        ('viewport_height', 320, 1920),
    ]:
        if type(values[key]) is not int or not lower <= values[key] <= upper:
            raise ValueError('Invalid app runtime budget')
    if type(values['app_writable_root']) is not bool:
        raise ValueError('app_writable_root must be boolean')
    profile = integration(task).get('environment_profile', 'generic' if platform == 'web' else platform)
    from gui_agent_bench.environment import preparation_for

    return {
        **values,
        'domain': data['metadata'].get('domain', platform),
        'platform': platform,
        'environment_profile': profile,
        'web_preparation': preparation_for(task),
    }


def browser_args(config):
    """Arguments shared by every trusted browser broker and capture helper."""
    from gui_agent_bench.environment import encode_preparation

    return [
        '--viewport-width',
        str(config['viewport_width']),
        '--viewport-height',
        str(config['viewport_height']),
        '--timezone',
        config['timezone'],
        '--platform',
        config['platform'],
        '--profile',
        config['environment_profile'],
        '--preparation',
        encode_preparation(config.get('web_preparation')),
    ]
