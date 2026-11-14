"""Public oracle API. Docker and the broker enforce its execution boundary."""

import base64
import json
import urllib.request
import urllib.error


class Page:
    def _call(self, operation, **arguments):
        request = urllib.request.Request(
            'http://browser:8081/call',
            data=json.dumps({'operation': operation, 'arguments': arguments}).encode(),
            headers={'Content-Type': 'application/json'},
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            # The trusted broker returns a static public message, never private detail.
            try:
                error = json.load(exc)
                message = error.get('message', 'GUI operation failed')
            except (ValueError, AttributeError):
                message = 'GUI operation failed'
            raise RuntimeError(message) from None
        if result.get('error'):
            raise RuntimeError('Oracle capability unavailable')
        return result.get('value')

    def screenshot(self):
        return base64.b64decode(self._call('screenshot'))

    def dump_ui(self):
        return self._call('ui')

    def reset(self):
        self._call('reset')

    def goto(self, url):
        self._call('open_url', url=url)

    def reload(self):
        self._call('step', action='reload')

    def click(self, x, y):
        self._call('step', action='click', x=x, y=y)

    def long_press(self, x, y):
        self._call('step', action='long_press', x=x, y=y)

    def open_app(self, app):
        self._call('step', action='open_app', app=app)

    def hover(self, x, y):
        self._call('step', action='hover', x=x, y=y)

    def scroll(self, dx, dy, *, x=None, y=None):
        arguments = {'action': 'scroll', 'dx': dx, 'dy': dy}
        if x is not None or y is not None:
            # The broker validates this profile-specific extension. Include
            # both fields even for malformed partial calls so denial remains
            # an evidenced execution-operation failure, not a silent fallback.
            arguments.update(x=x, y=y)
        self._call('step', **arguments)

    def type_text(self, text):
        self._call('step', action='type', text=text)

    def press(self, key):
        self._call('step', action='press', key=key)

    def get_by_role(self, role, *, name, exact=True):
        if exact is not True:
            raise ValueError('Only exact names are supported')
        return Locator(self, {'role': role, 'name': name})

    def get_by_text(self, text, *, exact=True):
        if exact is not True:
            raise ValueError('Only exact text is supported')
        return Locator(self, {'text': text})

    def expect_image(
        self,
        reference,
        *,
        region=None,
        masks=None,
        threshold=0.1,
        max_diff_pixels=0,
        include_aa=False,
        precondition=False,
        observation_window_ms=1600,
    ):
        """Compare pixels with a named screenshot sealed during authoring."""
        self._call(
            'assert',
            kind='image',
            reference=reference,
            region=region,
            masks=[] if masks is None else masks,
            threshold=threshold,
            max_diff_pixels=max_diff_pixels,
            include_aa=include_aa,
            precondition=precondition,
            observation_window_ms=observation_window_ms,
        )


class Locator:
    def __init__(self, page, query):
        self.page, self.query = page, query

    def _expect(self, condition, expected, precondition):
        self.page._call(
            'assert', kind='ui', query=self.query, condition=condition, expected=expected, precondition=precondition
        )

    def _act(self, action, **values):
        self.page._call('step', action=action, **self.query, **values)

    def click(self):
        self._act('click')

    def long_press(self):
        self._act('long_press')

    def hover(self):
        self._act('hover')

    def fill(self, text):
        self._act('fill', text=text)

    def press(self, key):
        self._act('press', key=key)

    def to_be_visible(self, *, precondition=False):
        self._expect('visible', True, precondition)

    def to_be_hidden(self, *, precondition=False):
        self._expect('visible', False, precondition)

    def to_have_text(self, text, *, precondition=False):
        self._expect('text', text, precondition)

    def to_have_value(self, value, *, precondition=False):
        self._expect('value', value, precondition)

    def to_have_count(self, count, *, precondition=False):
        self._expect('count', count, precondition)
