"""Isolated browser owner. Generated Python never shares this process or filesystem.

Authoring uses MCP; execution exposes read-only observations and assertions.
Only this process can write the assertion ledger consumed by the controller.
"""

import argparse
import base64
from http.server import HTTPServer
import json
from pathlib import Path
import runpy
import time

from gui_agent_bench.adapters.factory import adapter_for
from gui_agent_bench.broker import TOOLS, schema, validate_call, platform_tools
from gui_agent_bench.io import strict_json
from gui_agent_bench.budgets import author_broker_posts
from gui_agent_bench.http_transport import ClosingJSONHandler, serve_gui
from gui_agent_bench.actions import step_tool, execute_step
from gui_agent_bench.failures import Failure, checked, issue, public_error
from gui_agent_bench.visual import ImageAssertions, ReferenceStore, reference_name, validate_image_assertion
from gui_agent_bench.coordinates import OBSERVE_DESCRIPTION, observation_content

ARMS = {'oracle_visual', 'oracle_ui', 'test_visual', 'test_ui'}


def _tools_for(arm):
    if arm not in ARMS:
        raise ValueError('unknown oracle arm')
    if arm == 'test_ui':
        return TOOLS
    if arm == 'test_visual':
        return [
            {**t, 'description': 'Reset to a fresh application home page.'} if t['name'] == 'reset' else t
            for t in tools_for('oracle_visual')
        ]
    if arm == 'oracle_ui':
        return [
            {**t, 'description': 'Restore the prepared final checkpoint.'} if t['name'] == 'reset' else t for t in TOOLS
        ]
    step = step_tool()
    return [
        (
            step
            if t['name'] == 'step'
            else {**t, 'description': 'Restore the prepared final checkpoint.'} if t['name'] == 'reset' else t
        )
        for t in TOOLS
        if t['name'] != 'dump_ui'
    ]


def tools_for(arm):
    return [
        (
            {
                **tool,
                'description': OBSERVE_DESCRIPTION
                + 'Optionally save an immutable named reference for expect_image; choose a new name for each capture.',
                'inputSchema': schema({'reference': {'type': 'string', 'pattern': '^[a-z][a-z0-9_-]{0,47}$'}}, []),
            }
            if tool['name'] == 'observe'
            else tool
        )
        for tool in _tools_for(arm)
    ]


def prepare(adapter, source):
    """Stop at the admitted final checkpoint, before its private assertion."""

    class CheckpointReached(BaseException):
        pass

    from gui_agent_bench.tv import checkpoint_count

    admitted = runpy.run_path(str(source))
    count = checkpoint_count(admitted)
    steps = []

    def checkpoint(description):
        if not isinstance(description, str) or len(description) > 2000:
            raise ValueError('invalid checkpoint description')
        steps.append(description)
        if len(steps) == count:
            raise CheckpointReached()

    adapter.reset()
    try:
        admitted['test_behavior'](adapter.page, checkpoint)
    except CheckpointReached:
        if getattr(adapter, 'platform', 'web') == 'web':
            adapter.wait_ready()
        print(json.dumps({'setup': 'ready', 'steps': steps}), flush=True)
        return steps
    raise RuntimeError('Final checkpoint not reached')


def validate_assertion(args, arm, viewport):
    if not isinstance(args, dict) or type(args.get('precondition')) is not bool:
        raise ValueError('invalid assertion')
    if args.get('kind') == 'image':
        validate_image_assertion(args, viewport)
        return
    if not arm.endswith('_ui') or args.get('kind') != 'ui':
        raise Failure('policy_violation')
    if set(args) != {'kind', 'query', 'condition', 'expected', 'precondition'}:
        raise ValueError('unknown assertion fields')
    query = args['query']
    if not isinstance(query, dict) or set(query) not in ({'text'}, {'role', 'name'}):
        raise ValueError('only exact role/name or text queries')
    from gui_agent_bench.ui_contract import validate_role_name, positive_precondition

    if 'role' in query:
        validate_role_name(query['role'], query['name'])
    elif not isinstance(query['text'], str) or not 1 <= len(query['text']) <= 200:
        raise ValueError('query budget')
    condition, expected = args['condition'], args['expected']
    if args['precondition'] and not positive_precondition(condition, expected):
        raise ValueError('precondition must positively identify the screen')
    if condition == 'visible' and type(expected) is bool:
        return
    if condition in {'text', 'value'} and isinstance(expected, str) and len(expected) <= 2000:
        return
    if condition == 'count' and type(expected) is int and 0 <= expected <= 100:
        return
    raise ValueError('assertion denied')


def check_assertion(adapter, args):
    if getattr(adapter, 'platform', 'web') == 'mobile':
        return adapter.assert_ui(args)
    adapter.wait_ready()
    from playwright.sync_api import expect

    query = args['query']
    locator = (
        adapter.page.get_by_text(query['text'], exact=True)
        if 'text' in query
        else adapter.page.get_by_role(query['role'], name=query['name'], exact=True)
    )
    started = time.monotonic()
    try:
        if args['condition'] != 'count' and locator.count() > 1:
            raise Failure('target_ambiguous')
        assertion = expect(locator)
        condition, expected = args['condition'], args['expected']
        if condition == 'visible':
            (assertion.to_be_visible if expected else assertion.not_to_be_visible)(timeout=1500)
        elif condition == 'text':
            assertion.to_have_text(expected, timeout=1500)
        elif condition == 'value':
            assertion.to_have_value(expected, timeout=1500)
        else:
            assertion.to_have_count(expected, timeout=1500)
        return True
    except AssertionError:
        return False
    except Exception as exc:
        adapter.diagnose_target(exc, locator, started, stage='ui_assertion')
        raise


def serve(
    arm,
    mode,
    source,
    viewport=(1280, 720),
    timezone='UTC',
    platform='web',
    *,
    reference_root=Path('/tmp/references'),
    execution_references=Path('/references'),
    evidence_root=Path('/tmp/image-assertions'),
    profile='generic',
    preparation=None,
):
    if arm not in ARMS or mode not in {'author', 'execute'}:
        raise ValueError('broker mode denied')
    if platform == 'tv' and arm not in {'oracle_visual', 'test_visual'}:
        raise ValueError('TV UI arms are unavailable')
    adapter = adapter_for(platform, 'http://app:8000/', viewport, timezone, profile, preparation)

    def reset():
        try:
            if arm.startswith('test_'):
                adapter.reset()
                print(json.dumps({'setup': 'ready', 'initial_state': True}), flush=True)
            else:
                prepare(adapter, source)
        except Exception as exc:
            raise Failure('reset_failure') from exc

    try:
        reset()
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
    calls = 0
    post_limit = author_broker_posts(arm) if mode == 'author' else 80
    references = ReferenceStore(reference_root, viewport) if mode == 'author' else None
    images = ImageAssertions(execution_references, evidence_root, viewport) if mode == 'execute' else None

    def act(name, args):
        if name == 'observe':
            if not isinstance(args, dict) or set(args) not in (set(), {'reference'}):
                raise Failure('invalid_arguments')
            if args:
                checked(reference_name, args['reference'])
            return
        if platform == 'tv':
            from gui_agent_bench.tv import validate_call as validate_tv_call

            checked(validate_tv_call, name, args)
            if name == 'reset':
                reset()
            else:
                adapter.visual_step(args)
            return
        if name == 'step':
            execute_step(adapter, args, viewport, ui=arm.endswith('_ui'), platform=platform)
        else:
            checked(validate_call, name, args)
            if name == 'reset':
                reset()
            elif name == 'open_url':
                adapter.open_url(args['url'])

    def log(**record):
        print(json.dumps(record), flush=True)

    def log_failure(exc, op_name, **fields):
        failure = issue(
            exc,
            phase='execution' if mode == 'execute' else 'authoring',
            operation=op_name,
            impact='zero_credit' if mode == 'execute' else 'feedback',
        )
        log(operation_failed=True, denied=failure['cause'] == 'policy_violation', failure=failure, **fields)

    from gui_agent_bench.authoring_recovery import AuthoringRecovery

    recovery = AuthoringRecovery(platform, reset, log) if mode == 'author' else None

    class Handler(ClosingJSONHandler):
        def log_message(self, *_):
            pass

        def send_error(self, code, message=None, explain=None):
            # BaseHTTPRequestHandler rejects unsupported HTTP verbs here.
            # Keep those denials in the same authoritative execution ledger.
            log_failure(Failure('policy_violation'), 'http_protocol', operation='http_protocol')
            super().send_error(code, message, explain)

        def do_GET(self):
            if mode == 'author' and self.path == '/mcp':
                return self.reply(405)
            if self.path != '/health':
                log_failure(Failure('policy_violation'), 'http_get', operation='http_get')
                return self.reply(403, {'error': True})
            self.reply(200, {'ready': True, 'platform': platform})

        def do_POST(self):
            nonlocal calls
            calls += 1
            request_id = None
            method = None
            name, args = None, None
            operation = 'protocol'
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if calls > post_limit:
                    raise Failure('budget_exhausted')
                if not 0 < length <= 16384:
                    raise Failure('evidence_overflow')
                if self.headers.get('Origin') or self.headers.get('Transfer-Encoding'):
                    raise Failure('policy_violation')
                request = checked(strict_json, self.rfile.read(length))
                if not isinstance(request, dict):
                    raise Failure('invalid_arguments')
                if mode == 'execute':
                    if self.path != '/call' or set(request) != {'operation', 'arguments'}:
                        raise Failure('policy_violation')
                    op, args = request['operation'], request['arguments']
                    operation = (
                        op
                        if isinstance(op, str) and op in {'screenshot', 'ui', 'step', 'open_url', 'reset', 'assert'}
                        else 'unknown'
                    )
                    if op == 'screenshot' and args == {}:
                        value = base64.b64encode(adapter.observe()).decode()
                    elif op == 'ui' and args == {} and arm.endswith('_ui'):
                        value = adapter.dump_ui()
                        if len(value.encode()) > 32000:
                            raise Failure('evidence_overflow')
                    elif op in {'step', 'open_url', 'reset'} and arm.startswith('test_'):
                        act(op, args)
                        log(action={'operation': op, 'arguments': args})
                        value = None
                    elif op == 'assert':
                        checked(validate_assertion, args, arm, viewport)
                        if args['kind'] == 'image':
                            comparison = images.observe_and_check(adapter.observe, args)
                            log(assertion=args, matched=comparison['matched'], image=comparison)
                        else:
                            log(assertion=args, matched=check_assertion(adapter, args))
                        value = None  # Failed checks stay in the trusted ledger even if code ignores them.
                    else:
                        raise Failure('policy_violation')
                    log(operation=op, denied=False)
                    return self.reply(200, {'value': value})
                if self.path != '/mcp' or request.get('jsonrpc') != '2.0':
                    raise Failure('policy_violation')
                request_id, method = request.get('id'), request.get('method')
                if method == 'notifications/initialized':
                    return self.reply(202)
                if method == 'initialize':
                    result = {
                        'protocolVersion': '2024-11-05',
                        'capabilities': {'tools': {}},
                        'serverInfo': {'name': 'gui', 'version': '0.3.0'},
                    }
                elif method == 'tools/list':
                    result = {'tools': platform_tools(tools_for(arm), platform, profile)}
                elif method == 'ping':
                    result = {}
                elif method == 'tools/call':
                    name = request['params']['name']
                    args = request['params'].get('arguments', {})
                    operation = name if isinstance(name, str) and name in {t['name'] for t in TOOLS} else 'unknown'
                    if name not in {t['name'] for t in platform_tools(tools_for(arm), platform, profile)}:
                        raise Failure('policy_violation')
                    recovery.check()
                    act(name, args)
                    if name == 'observe':
                        png = adapter.observe()
                        content = observation_content(png, viewport, platform)
                        if 'reference' in args:
                            entry = references.capture(args['reference'], png)
                            content.append({'type': 'text', 'text': 'Saved image reference: ' + args['reference']})
                            log(reference={'name': args['reference'], **entry})
                    else:
                        value = adapter.dump_ui() if name == 'dump_ui' else 'Action completed.'
                        if len(value.encode()) > 32000:
                            raise Failure('evidence_overflow')
                        content = [{'type': 'text', 'text': value}]
                    result = {'content': content, 'isError': False}
                    log(tool=name, arguments=args, denied=False)
                else:
                    raise Failure('policy_violation')
                self.reply(200, {'jsonrpc': '2.0', 'id': request_id, 'result': result})
            except Exception as exc:
                if (
                    operation == 'protocol'
                    and isinstance(exc, (ValueError, KeyError, TypeError))
                    and not isinstance(exc, Failure)
                ):
                    exc = Failure('invalid_arguments')
                if mode == 'author':
                    result, failure, recovered = recovery.handle(exc, operation)
                    log(
                        operation_failed=True,
                        denied=failure['cause'] == 'policy_violation',
                        failure=failure,
                        **({'tool': name, 'arguments': args} if name else {}),
                        **({'recovery': recovered} if recovered else {}),
                    )
                    self.reply(200, {'jsonrpc': '2.0', 'id': request_id, 'result': result})
                else:
                    log_failure(exc, operation, **({'tool': name, 'arguments': args} if name else {}))
                    self.reply(400, {'error': True, **public_error(exc)})

    try:
        serve_gui(HTTPServer(('0.0.0.0', 8081), Handler), adapter, platform)
    finally:
        adapter.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--arm', choices=sorted(ARMS), required=True)
    parser.add_argument('--mode', choices=['author', 'execute'], required=True)
    parser.add_argument('--source', type=Path, default=Path('/setup/source.py'))
    parser.add_argument('--viewport-width', type=int, default=1280)
    parser.add_argument('--viewport-height', type=int, default=720)
    parser.add_argument('--timezone', default='UTC')
    parser.add_argument('--platform', choices=['web', 'mobile', 'tv'], default='web')
    parser.add_argument('--profile', default='generic')
    parser.add_argument('--preparation', default='{}')
    args = parser.parse_args()
    from gui_agent_bench.environment import decode_preparation

    serve(
        args.arm,
        args.mode,
        args.source,
        (args.viewport_width, args.viewport_height),
        args.timezone,
        args.platform,
        profile=args.profile,
        preparation=decode_preparation(args.preparation),
    )
