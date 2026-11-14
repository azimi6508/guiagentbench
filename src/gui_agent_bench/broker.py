"""Small stateless MCP server exposing only bounded browser primitives.

The browser lives here, without task sources, labels, credentials or a shell
tool. The evaluated process cannot reach the application network directly.
"""

from http.server import HTTPServer
import json

from gui_agent_bench.io import strict_json
from gui_agent_bench.budgets import author_tool_calls
from gui_agent_bench.http_transport import ClosingJSONHandler, serve_gui
from gui_agent_bench.actions import step_tool, validate_step, execute_step
from gui_agent_bench.failures import Failure, checked, issue
from gui_agent_bench.coordinates import OBSERVE_DESCRIPTION, observation_content
from gui_agent_bench.ui_contract import validate_role_name


def schema(properties=None, required=()):
    return {'type': 'object', 'properties': properties or {}, 'required': list(required), 'additionalProperties': False}


TOOLS = [
    {'name': 'observe', 'description': OBSERVE_DESCRIPTION, 'inputSchema': schema()},
    {
        'name': 'dump_ui',
        'description': 'Get the current accessibility tree (roles, names and text).',
        'inputSchema': schema(),
    },
    {'name': 'reset', 'description': 'Reset the app and browser to the initial state.', 'inputSchema': schema()},
    {
        'name': 'open_url',
        'description': 'Open the application home page. Only http://app:8000/ is allowed.',
        'inputSchema': schema({'url': {'type': 'string', 'enum': ['http://app:8000/']}}, ['url']),
    },
    step_tool(ui=True),
]


def platform_tools(tools, platform, profile="generic"):
    if platform == 'web':
        return tools
    if platform == 'tv':
        from gui_agent_bench.tv import tools_for

        return tools_for(tools)
    if platform != 'mobile':
        raise ValueError('unknown platform')
    descriptions = {
        'dump_ui': 'Visible native Android nodes: roles, names, text, bounds and state. No DOM.',
        'open_url': 'Open the task app home. http://app:8000/ is the only logical home alias.',
        'step': f'Native touch/input: hover unavailable; coordinate taps require {68 if profile == "native_extended" else 128} <= y < {1184 if profile == "native_extended" else 1244}. Reload closes and reopens the app. ',
    }
    result = []
    for tool in tools:
        tool = json.loads(json.dumps(tool))
        tool['description'] = (
            descriptions['step'] + tool['description']
            if tool['name'] == 'step'
            else descriptions.get(tool['name'], tool['description'])
        )
        if tool['name'] == 'step':
            tool['inputSchema']['properties']['action']['enum'].remove('hover')
        if tool['name'] == 'step' and profile == 'native_extended':
            tool['inputSchema']['properties']['action']['enum'] += ['long_press', 'open_app']
            tool['inputSchema']['properties']['app'] = {'type': 'string', 'minLength': 1, 'maxLength': 100}
            tool[
                'description'
            ] += ' Native extension: long_press uses x,y (or exact role,name in UI arms); open_app uses app, an exact task-declared app name. No arbitrary packages. Extended native scroll requires dx,dy and optionally both x,y as its visible gesture origin; origin and clamped endpoint stay inside 68 <= y < 1184. A scroll remains one action. Default origin is (360,650).'
        result.append(tool)
    return result


def validate_call(name, args):
    if not isinstance(args, dict):
        raise ValueError('arguments must be an object')
    if name in {'observe', 'dump_ui', 'reset'} and not args:
        return
    if name == 'open_url' and args == {'url': 'http://app:8000/'}:
        return
    if name == 'open_url' or name not in {'step', 'observe', 'dump_ui', 'reset'}:
        raise Failure('policy_violation')
    if name != 'step':
        raise ValueError('tool or arguments denied')
    action = args.get('action')
    if isinstance(action, str) and action not in {'click', 'long_press', 'hover', 'fill', 'press', 'reload'}:
        raise Failure('policy_violation')
    if action == 'reload' and args == {'action': 'reload'}:
        return
    fields = {'action', 'role', 'name'} | ({'text'} if action == 'fill' else {'key'} if action == 'press' else set())
    if action not in {'click', 'long_press', 'hover', 'fill', 'press'} or set(args) != fields:
        raise ValueError('only a single allowlisted user action is accepted')
    validate_role_name(args['role'], args['name'])
    if action == 'fill' and (not isinstance(args['text'], str) or len(args['text']) > 2000):
        raise ValueError('text budget exceeded')
    if action == 'press' and args['key'] not in {
        'Enter',
        'Tab',
        'Escape',
        'ArrowDown',
        'ArrowUp',
        'ArrowLeft',
        'ArrowRight',
        'Backspace',
    }:
        raise ValueError('key denied')


def serve(viewport=(1280, 720), timezone='UTC', platform='web', profile='generic', preparation=None):
    from gui_agent_bench.adapters.factory import adapter_for

    adapter = adapter_for(platform, 'http://app:8000/', viewport, timezone, profile, preparation)
    try:
        adapter.reset()
    except Exception as exc:
        print(
            json.dumps(
                {
                    'operation_failed': True,
                    'failure': issue(exc, phase='setup', operation='reset', impact='zero_credit'),
                }
            ),
            flush=True,
        )
        adapter.close()
        raise
    from gui_agent_bench.authoring_recovery import AuthoringRecovery

    recovery = AuthoringRecovery(platform, adapter.reset, lambda **record: print(json.dumps(record), flush=True))
    calls = 0

    class Handler(ClosingJSONHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.reply(
                200 if self.path == '/health' else 405,
                {'ready': True, 'platform': platform} if self.path == '/health' else {},
            )

        def do_POST(self):
            print(
                json.dumps(
                    {
                        'protocol_http': 'POST',
                        'path': self.path,
                        'content_length': self.headers.get('Content-Length'),
                        'transfer_encoding': self.headers.get('Transfer-Encoding'),
                        'origin_present': bool(self.headers.get('Origin')),
                    }
                ),
                flush=True,
            )
            nonlocal calls
            if self.path != '/mcp' or self.headers.get('Origin') or self.headers.get('Transfer-Encoding'):
                self.log_failure(Failure('policy_violation'), 'protocol')
                return self.reply(403)
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                self.log_failure(Failure('invalid_arguments'), 'protocol')
                return self.reply(400)
            if not 0 < length <= 16384:
                self.log_failure(Failure('evidence_overflow'), 'protocol')
                return self.reply(413)
            request_id = None
            try:
                request = checked(strict_json, self.rfile.read(length))
                request_id = request.get('id')
                method, params = request['method'], request.get('params', {})
                if method != 'tools/call':
                    print(json.dumps({'protocol_method': method}), flush=True)
                if request.get('jsonrpc') != '2.0':
                    raise ValueError('invalid protocol')
                if method == 'notifications/initialized':
                    return self.reply(202)
                if method == 'initialize':
                    result = {
                        'protocolVersion': '2024-11-05',
                        'capabilities': {'tools': {}},
                        'serverInfo': {'name': 'gui', 'version': '0.2.0'},
                    }
                elif method == 'tools/list':
                    result = {'tools': platform_tools(TOOLS, platform, profile)}
                elif method == 'ping':
                    result = {}
                elif method == 'tools/call':
                    calls += 1
                    name, args = params['name'], params.get('arguments', {})
                    failure = None
                    recovered = None
                    try:
                        if calls > author_tool_calls('judge_test'):
                            raise Failure('budget_exhausted')
                        recovery.check()
                        if platform == 'tv':
                            from gui_agent_bench.tv import validate_call as validate_tv_call

                            checked(validate_tv_call, name, args)
                        elif name == 'step':
                            checked(
                                validate_step,
                                args,
                                viewport,
                                ui=True,
                                platform=platform,
                                mobile_touch_top=68 if profile == 'native_extended' else 128,
                            )
                        else:
                            checked(validate_call, name, args)
                        if name == 'observe':
                            content = observation_content(adapter.observe(), viewport, platform)
                        else:
                            if name == 'dump_ui':
                                value = adapter.dump_ui()
                                if len(value.encode()) > 32000:
                                    raise Failure('evidence_overflow')
                            else:
                                if name == 'reset':
                                    try:
                                        adapter.reset()
                                    except Exception as exc:
                                        raise Failure('reset_failure') from exc
                                elif name == 'open_url':
                                    adapter.open_url(args['url'])
                                elif platform == 'tv':
                                    adapter.user_step(args)
                                else:
                                    execute_step(adapter, args, viewport, ui=True, platform=platform)
                                value = 'Action completed.'
                            content = [{'type': 'text', 'text': value}]
                        result = {'content': content, 'isError': False}
                    except Exception as exc:
                        result, failure, recovered = recovery.handle(
                            exc, name if name in {t['name'] for t in TOOLS} else 'unknown'
                        )
                    print(
                        json.dumps(
                            {
                                'tool': name,
                                'arguments': args,
                                'denied': bool(failure and failure['cause'] == 'policy_violation'),
                                'operation_failed': failure is not None,
                                **({'failure': failure} if failure else {}),
                                **({'recovery': recovered} if recovered else {}),
                            }
                        ),
                        flush=True,
                    )
                else:
                    raise ValueError('method denied')
                self.reply(200, {'jsonrpc': '2.0', 'id': request_id, 'result': result})
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                self.log_failure(exc if isinstance(exc, Failure) else Failure('invalid_arguments'), 'protocol')
                self.reply(
                    200, {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32600, 'message': 'Request denied'}}
                )

        def log_failure(self, exc, operation):
            failure = issue(exc, phase='authoring', operation=operation, impact='feedback')
            print(
                json.dumps(
                    {'operation_failed': True, 'denied': failure['cause'] == 'policy_violation', 'failure': failure}
                ),
                flush=True,
            )

    try:
        serve_gui(HTTPServer(('0.0.0.0', 8081), Handler), adapter, platform)
    finally:
        adapter.close()
