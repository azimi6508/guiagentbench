"""Screen/remote transport; only admitted reference code calls check_goal."""

import base64
import hashlib
from gui_agent_bench.environment import emit
import json
import time
import urllib.request

from gui_agent_bench.tv import validate_step
from gui_agent_bench.failures import Failure


class TVAdapter:
    platform = 'tv'

    def __init__(self, base_url='http://app:8000/', viewport=(960, 540), timezone='UTC'):
        self.base_url = base_url.rstrip('/')
        self.viewport = viewport
        self.page = self
        deadline = time.monotonic() + 40
        while True:
            try:
                if self.call('ready') is not True:
                    raise ValueError('TV readiness response differs')
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('TV app did not finish verifying its frozen assets')
                time.sleep(0.25)

    def call(self, operation, **arguments):
        request = urllib.request.Request(
            self.base_url + '/call',
            data=json.dumps({'operation': operation, 'arguments': arguments}).encode(),
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)
        if result == {'error': True, 'cause': 'simulator_ambiguity'}:
            raise Failure('simulator_ambiguity')
        if set(result) != {'value'}:
            raise RuntimeError('TV operation unavailable')
        return result['value']

    def reset(self):
        self.call('reset')
        emit('reset', 'tv', status='ready', screenshot_sha256=hashlib.sha256(self.observe()).hexdigest())

    def observe(self):
        return base64.b64decode(self.call('screenshot'), validate=True)

    def user_step(self, args):
        validate_step(args)
        self.call('step', **args)

    visual_step = user_step

    def press(self, key):
        self.user_step({'action': 'press', 'key': key})

    def check_goal(self):
        return self.call('reference_check') is True

    def dump_ui(self):
        raise ValueError('TV has no independently observed UI tree')

    def open_url(self, _url):
        raise ValueError('TV has no URL navigation')

    def close(self):
        pass
