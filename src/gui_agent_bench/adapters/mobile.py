"""Trusted remote native-Android adapter; no device addresses reach clients."""

import base64
import hashlib
from gui_agent_bench.environment import emit
import json
import urllib.request
import urllib.error
from gui_agent_bench.failures import Failure, MESSAGES
from gui_agent_bench.failure_detail import attach, restore


def remote_failure(result, fallback):
    cause = result.get('cause') if isinstance(result, dict) else None
    failure = Failure(cause if isinstance(cause, str) and cause in MESSAGES else fallback)
    if isinstance(result, dict) and 'detail' in result:
        try:
            restore(failure, result['detail'])
        except (ValueError, TypeError):
            # Reject malformed metadata; never forward or print its contents.
            return attach(
                Failure('infrastructure_error'),
                component='native_adapter',
                stage='transport',
                facts={'diagnostic_valid': False},
            )
    return failure


class MobileAdapter:
    platform = 'mobile'

    def __init__(self, base_url='http://app:8000/', viewport=(720, 1280), timezone='UTC', profile='mobile'):
        if profile not in ('generic', 'mobile', 'native_extended'):
            raise ValueError('Unsupported native profile')
        self.mobile_touch_top = 68 if profile == 'native_extended' else 128
        self.profile = profile
        self.base_url, self.viewport = base_url.rstrip('/'), viewport
        self.page = self  # Limited API for the admitted reference setup only.

    def call(self, operation, **arguments):
        request = urllib.request.Request(
            self.base_url + '/call',
            data=json.dumps({'operation': operation, 'arguments': arguments}).encode(),
            headers={'Content-Type': 'application/json'},
        )
        try:
            with urllib.request.urlopen(request, timeout=95) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                result = json.load(exc)
            except ValueError:
                raise Failure('infrastructure_error') from None
            raise remote_failure(result, 'infrastructure_error') from None
        except (urllib.error.URLError, TimeoutError) as exc:
            attach(exc, component='native_adapter', stage='transport')
            raise
        if result.get('error') is True:
            raise remote_failure(result, 'unknown_operation_error')
        if set(result) != {'value'}:
            raise RuntimeError('native operation unavailable')
        return result['value']

    def reset(self):
        self.call('reset')
        emit('reset', 'mobile', status='ready', screenshot_sha256=hashlib.sha256(self.observe()).hexdigest())

    def open_url(self, url):
        if url != 'http://app:8000/':
            raise ValueError('only the logical app home is allowed')
        self.call('home')

    def reload(self, **_):
        self.call('reload')

    def observe(self):
        return base64.b64decode(self.call('screenshot'), validate=True)

    def dump_ui(self):
        return self.call('ui')

    def user_step(self, args):
        self.call('step', **args)

    def visual_step(self, args):
        self.call('visual', **args)

    def assert_ui(self, args):
        return self.call('assert_ui', **args)

    def require_text(self, text):
        # Only used by the admitted reference. Generated code never sees this
        # adapter or its transport; it uses the separate sandbox client.
        assert self.assert_ui(
            {'kind': 'ui', 'query': {'text': text}, 'condition': 'visible', 'expected': True, 'precondition': False}
        ), 'Missing native text: ' + repr(text)

    def check_fixture(self):
        return self.call('check_fixture')

    def close(self):
        pass

    def install_app(self, _artifact):
        raise PermissionError('APK installation belongs to trusted mobile_setup only')
