"""Public, label-independent preparation contracts.

Browser-rendered applications declare their own preparation in the task
package (``[integration.web]`` in ``task.toml``). The controller validates the
declaration and passes it to the trusted browser broker, so a new application
never needs a framework-side profile.
"""

import hashlib
import json
import math
from datetime import datetime

from gui_agent_bench.ui_contract import ROLES

VERSION = 'environment-v1'
DEFAULT_RESET_TIMEOUT_SECONDS = 30
WEB_PREPARATION_FIELDS = frozenset({'ready', 'fixed_clock', 'wait_for_fonts', 'reset_timeout_sec'})


def web_preparation(value=None):
    """Return the canonical web preparation for a task declaration.

    ``ready`` lists visible landmarks (role and exact accessible name, or a
    test id) that mark the initial page as ready. ``fixed_clock`` pins the
    browser wall clock (timers stay real). ``wait_for_fonts`` waits for the
    initial font load. ``reset_timeout_sec`` bounds the application's reset.
    """
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - WEB_PREPARATION_FIELDS:
        raise ValueError('Unknown web preparation settings')
    ready = value.get('ready', [])
    if not isinstance(ready, list) or len(ready) > 8:
        raise ValueError('Declare at most eight readiness landmarks')
    landmarks = []
    for item in ready:
        if (
            isinstance(item, dict)
            and set(item) == {'test_id'}
            and isinstance(item['test_id'], str)
            and 0 < len(item['test_id']) <= 128
        ):
            landmarks.append({'test_id': item['test_id']})
        elif (
            isinstance(item, dict)
            and set(item) == {'role', 'name'}
            and item['role'] in ROLES
            and isinstance(item['name'], str)
            and 0 < len(item['name']) <= 128
        ):
            landmarks.append({'role': item['role'], 'name': item['name']})
        else:
            raise ValueError('A readiness landmark needs a role and exact name, or a test_id')
    clock = value.get('fixed_clock')
    if clock is not None:
        try:
            parsed = datetime.fromisoformat(clock) if isinstance(clock, str) else None
        except ValueError:
            parsed = None
        if parsed is None or parsed.tzinfo is None:
            raise ValueError('fixed_clock must be an ISO 8601 time with a UTC offset')
    fonts = value.get('wait_for_fonts', False)
    if type(fonts) is not bool:
        raise ValueError('wait_for_fonts must be true or false')
    reset = value.get('reset_timeout_sec', DEFAULT_RESET_TIMEOUT_SECONDS)
    if type(reset) not in {int, float} or not math.isfinite(reset) or not 1 <= reset <= 300:
        raise ValueError('reset_timeout_sec must be between 1 and 300')
    return {'ready': landmarks, 'fixed_clock': clock, 'wait_for_fonts': fonts, 'reset_timeout_sec': reset}


def encode_preparation(preparation):
    return json.dumps(web_preparation(preparation), sort_keys=True, separators=(',', ':'))


def decode_preparation(text):
    return web_preparation(json.loads(text) if text else None)


def preparation_for(task):
    from gui_agent_bench.task_package import integration

    return web_preparation(integration(task).get('web'))


def profile_for(task, platform):
    from gui_agent_bench.task_package import integration

    if (task / 'task.toml').is_file():
        return integration(task).get('environment_profile', 'generic' if platform == 'web' else platform)
    return 'generic' if platform == 'web' else platform


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def emit(event, platform, **fields):
    record = dict(environment_contract=VERSION, environment_event=event, platform=platform, **fields)
    print(json.dumps(record), flush=True)
    return record
