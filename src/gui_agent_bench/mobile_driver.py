"""Trusted host UIAutomator2 driver for one disposable, pinned research AVD.

This module never imports submissions. No shell, file path, package name,
selector expression, ADB command or URL is accepted from a GUI client.
"""

import argparse
import base64
import io
import json
import os
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from gui_agent_bench.failures import Failure
from gui_agent_bench.environment import emit, fingerprint
from gui_agent_bench.mobile_host import (
    sdk_path,
    sdk_tool,
    device_lock,
    native_environment,
    ROOT,
)  # noqa: F401 (sdk_path is re-exported)

SERIAL = 'emulator-5580'
AVD = 'GuiAgentBench'
VIEWPORT = (720, 1280)


def adb(*args, timeout=45):
    result = subprocess.run(
        [str(sdk_tool('adb')), '-s', SERIAL, *args],
        capture_output=True,
        timeout=timeout,
        check=True,
        env=native_environment(ROOT),
    )
    return result.stdout.decode('utf-8', 'replace').strip()


def safe_device():
    # Never default to the only connected device: it could be somebody's phone.
    name = adb('emu', 'avd', 'name').splitlines()[0]
    if name != AVD or adb('shell', 'getprop', 'sys.boot_completed') != '1':
        raise RuntimeError('dedicated research AVD is not booted')
    if adb('shell', 'getprop', 'ro.kernel.qemu') != '1':
        raise RuntimeError('physical devices are forbidden')


PACKAGE_NAME = r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+'
FOCUS_RECORD = re.compile(r'^\s*mCurrentFocus=Window\{([0-9a-f]+) u\d+ ([^\s{}]+)\}\s*$', re.MULTILINE)
OWNER_RECORD = re.compile(r'^\s+mOwnerUid=\d+ .*\bpackage=(' + PACKAGE_NAME + r')(?: |$)', re.MULTILINE)


def focused_package(*, timeout=10):
    # API36's scoped `dumpsys window windows` omits mCurrentFocus. adbutils
    # then searches obsolete mResumedActivity and can return a background app
    # from `activity top`. Read the full, real focused-window record instead.
    # Never guess from resumed/background activities, UI contents or recency.
    # The focused window may be an activity or an app-owned sub-window such as
    # a PopupWindow menu, whose title has no package. Its owner comes from the
    # same snapshot's window record, so a system dialog still reports its own
    # package and an app popup reports the app.
    output = adb('shell', 'dumpsys', 'window', timeout=timeout)
    focus = FOCUS_RECORD.findall(output)
    if len(focus) != 1:
        raise Failure('app_not_ready')
    token, title = focus[0]
    lines = output.splitlines()
    headers = [
        i
        for i, line in enumerate(lines)
        if re.fullmatch(r'(\s*)Window #\d+ Window\{' + token + r' u\d+ ' + re.escape(title) + r'\}:\s*', line)
    ]
    if len(headers) != 1:
        raise Failure('app_not_ready')
    start = headers[0]
    indent = len(lines[start]) - len(lines[start].lstrip())
    record = []
    for line in lines[start + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        record.append(line)
    owners = OWNER_RECORD.findall('\n'.join(record))
    if len(owners) != 1:
        raise Failure('app_not_ready')
    owner = owners[0]
    # An activity title names its package; it must agree with the owner.
    if '/' in title and title.split('/', 1)[0] != owner:
        raise Failure('app_not_ready')
    return owner


def wait_focused_package(package, timeout=15):
    # Ordinary bounded launch wait, not a trial retry or a stability gate.
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            current = focused_package(timeout=min(5, remaining))
        except Failure as exc:
            if exc.cause != 'app_not_ready':
                raise
            current = None
        if current == package and time.monotonic() < deadline:
            return
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    raise Failure('app_not_ready')


def nodes_from_xml(xml, package):
    """Native semantics, not fabricated DOM; IDs disambiguate unnamed widgets."""
    result = []
    for node in ET.fromstring(xml).iter('node'):
        a = node.attrib
        if a.get('package') != package:
            continue
        bounds = [int(x) for x in re.findall(r'\d+', a.get('bounds', ''))]
        if len(bounds) != 4 or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            continue
        cls = a.get('class', '')
        role = (
            'textbox'
            if cls.endswith('EditText')
            else (
                'checkbox'
                if a.get('checkable') == 'true'
                else (
                    'button' if a.get('clickable') == 'true' or cls.endswith(('Button', 'ImageButton')) else 'paragraph'
                )
            )
        )
        text, desc, resource = a.get('text', ''), a.get('content-desc', ''), a.get('resource-id', '')
        children = (
            ' '.join(
                child.attrib['text']
                for child in node.iter('node')
                if child is not node and child.attrib.get('package') == package and child.attrib.get('text')
            )
            if role in {'button', 'checkbox', 'textbox'}
            else ''
        )
        name = (
            desc or resource or a.get('hint') or text or children
            if role == 'textbox'
            else desc or text or children or resource
        )
        if name or text:
            result.append(
                {
                    'role': role,
                    'name': name,
                    'text': text,
                    'bounds': bounds,
                    'enabled': a.get('enabled') == 'true',
                    'focused': a.get('focused') == 'true',
                }
            )
    return result


class Driver:
    def __init__(self, root, application, app_record, platform_record=None):
        if application is None or not isinstance(app_record, dict) or not app_record.get('package'):
            raise ValueError('A verified task-owned native fixture is required')
        safe_device()
        from gui_agent_bench.mobile_runtime import verify_runtime

        self.runtime = dict(platform_record if platform_record is not None else verify_runtime(root))
        import uiautomator2 as u2

        self.device = u2.connect(SERIAL)
        self.device.set_input_ime(True)
        self.root = root
        self.application = application
        self.package = app_record['package']
        self.runtime['task_application'] = dict(app_record)

    def foreground(self):
        if focused_package() != self.package:
            raise Failure('app_scope_lost')

    def nodes(self):
        self.foreground()
        return nodes_from_xml(self.device.dump_hierarchy(), self.package)

    def settle(self):
        # Poll actual UI structure/bounds until quiet, with a hard failure on
        # timeout. No fixed post-action sleep and no success on timeout.
        started = time.monotonic()
        deadline, stable_since, previous = started + 12, None, None
        while time.monotonic() < deadline:
            current = [{k: v for k, v in n.items() if k != 'focused'} for n in self.nodes()]
            now = time.monotonic()
            if current and current == previous:
                if stable_since is not None and now - stable_since >= 0.6 and now < deadline:
                    emit(
                        'readiness',
                        'mobile',
                        status='ready',
                        elapsed_ms=round((now - started) * 1000),
                        state_sha256=fingerprint(current),
                    )
                    return
            else:
                stable_since = now
            previous = current
            time.sleep(0.15)
        emit('readiness', 'mobile', status='timeout', elapsed_ms=round((time.monotonic() - started) * 1000))
        raise Failure('app_not_ready')

    def _lifecycle(self, operation):
        getattr(self.application, operation)(self.device, adb)
        wait_focused_package(self.package)
        self.settle()

    def launch(self):
        self._lifecycle('launch')

    def reset(self):
        safe_device()
        self.device.app_clear(self.package)
        # Clear cross-trial device state independently of app or task behavior.
        adb('shell', 'find /sdcard/ -mindepth 1 -maxdepth 1 ! -name Android -exec rm -rf {} \\;')
        adb('shell', 'rm', '-rf', '/sdcard/Android/media')
        if adb('shell', 'find /sdcard/ -path /sdcard/Android -prune -o -type f -print'):
            raise RuntimeError('shared native storage was not reset')
        cleared = adb(
            'shell',
            'service',
            'call',
            'clipboard',
            '3',
            's16',
            'com.android.shell',
            's16',
            'null',
            'i32',
            '0',
            'i32',
            '0',
        )
        if not re.fullmatch(r"Result: Parcel\(\s*00000000\s*'\.\.\.\.'\)", cleared):
            raise RuntimeError('native clipboard reset failed')
        adb('shell', 'cmd', 'alarm', 'set-timezone', 'UTC')
        for setting in ('window_animation_scale', 'transition_animation_scale', 'animator_duration_scale'):
            adb('shell', 'settings', 'put', 'global', setting, '0')
        adb('shell', 'svc', 'wifi', 'disable')
        adb('shell', 'svc', 'data', 'disable')
        self._lifecycle('reset')

    def reload(self):
        self.foreground()
        self._lifecycle('reload')

    def match(self, query):
        nodes = self.nodes()
        return (
            [n for n in nodes if n['text'] == query['text']]
            if 'text' in query
            else [n for n in nodes if (n['role'], n['name']) == (query['role'], query['name'])]
        )

    def assert_ui(self, args):
        from gui_agent_bench.oracle_broker import validate_assertion

        validate_assertion(args, 'test_ui', VIEWPORT)
        matches = self.match(args['query'])
        expected, condition = args['expected'], args['condition']
        if condition == 'count':
            return len(matches) == expected
        if condition == 'visible':
            return (len(matches) > 0) == expected
        return len(matches) == 1 and matches[0]['text'] == expected

    def step(self, args, visual=False):
        from gui_agent_bench.broker import validate_call
        from gui_agent_bench.actions import validate_visual_step

        if visual:
            validate_visual_step(args, VIEWPORT)
        else:
            validate_call('step', args)
        action = args['action']
        if action == 'reload':
            return self.reload()
        if action == 'hover':
            raise ValueError('hover is not a native touch capability')
        self.foreground()
        if visual:
            if action == 'click':
                # Keep status/navigation bars outside the task's action surface.
                if not 128 <= args['y'] < 1244:
                    raise ValueError('system navigation is outside the task')
                self.device.click(args['x'], args['y'])
            elif action == 'type':
                self.device.send_keys(args['text'], clear=False)
            elif action == 'press':
                self.key(args['key'])
            elif action == 'scroll':
                x, y = 360, 640
                self.device.swipe(x, y, max(1, min(719, x - args['dx'])), max(128, min(1243, y - args['dy'])), 0.3)
        else:
            matches = self.match({'role': args['role'], 'name': args['name']})
            if len(matches) != 1 or not matches[0]['enabled']:
                from gui_agent_bench.failure_detail import attach

                raise attach(
                    Failure('target_unavailable'),
                    component='native_driver',
                    stage='target_action',
                    facts={
                        'target_matches': len(matches),
                        'observation': 'before_action',
                        **({'enabled': matches[0]['enabled']} if len(matches) == 1 else {}),
                    },
                )
            x1, y1, x2, y2 = matches[0]['bounds']
            self.device.click((x1 + x2) // 2, (y1 + y2) // 2)
            if action == 'fill':
                if args['role'] != 'textbox':
                    raise ValueError('fill requires a textbox')
                self.device.send_keys(args['text'], clear=True)
            elif action == 'press':
                self.key(args['key'])
        self.settle()

    def key(self, key):
        mapping = {
            'Enter': 'enter',
            'Tab': 'tab',
            'Escape': 'back',
            'ArrowDown': 'down',
            'ArrowUp': 'up',
            'ArrowLeft': 'left',
            'ArrowRight': 'right',
            'Backspace': 'del',
        }
        self.device.press(mapping[key])

    def call(self, op, args):
        if not isinstance(args, dict):
            raise ValueError('arguments must be an object')
        if op in {'step', 'visual'}:
            return self.step(args, op == 'visual')
        if op == 'assert_ui':
            return self.assert_ui(args)
        if args:
            raise ValueError('unexpected arguments')
        if op == 'reset':
            return self.reset()
        if op == 'home':
            return self.launch()
        if op == 'reload':
            return self.reload()
        if op == 'ui':
            return json.dumps(self.nodes(), ensure_ascii=False)
        if op == 'screenshot':
            self.foreground()
            stream = io.BytesIO()
            self.device.screenshot().save(stream, format='PNG')
            return base64.b64encode(stream.getvalue()).decode()
        if op == 'check_fixture':
            # Private capture callback, absent from every evaluated tool catalog.
            check = getattr(self.application, 'check', None)
            if not callable(check):
                raise ValueError('This fixture has no private checker')
            value = check(self.device, adb)
            if type(value) is not bool:
                raise ValueError('Private fixture checks must return a boolean')
            return value
        raise ValueError('native operation denied')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--task', required=True)
    parser.add_argument('--variant', choices=['correct', 'faulty'], required=True)
    parser.add_argument('--relay-container', required=True)
    parser.add_argument('--record', required=True, type=Path)
    args = parser.parse_args()
    # OS-owned lock releases on crashes as well as ordinary cleanup.
    with device_lock(args.root):
        secret = os.environ.pop('GAB_RENDEZVOUS')
        from gui_agent_bench.mobile_runtime import verify_runtime
        from gui_agent_bench.native_application import load_fixture

        safe_device()
        platform = verify_runtime(args.root)
        application, record = load_fixture(args.root, args.task, args.variant)
        driver = Driver(args.root, application, record, platform)

        def request(path, value):
            result = subprocess.run(
                ['docker', 'exec', '-i', args.relay_container, 'python', '-m', 'gui_agent_bench.mobile_channel'],
                input=json.dumps({'secret': secret, 'path': path, 'value': value}).encode(),
                capture_output=True,
                timeout=35,
                check=True,
            )
            return json.loads(result.stdout)

        if request('/ready', {}) != {'ready': True}:
            raise RuntimeError('private native rendezvous not ready')
        args.record.write_text(json.dumps(driver.runtime, indent=2), encoding='utf-8')
        while True:
            work = request('/next', {})
            if work is None:
                continue
            started = time.monotonic()
            try:
                result = {'value': driver.call(work['operation'], work['arguments'])}
                print(json.dumps({'operation': work['operation'], 'ok': True}), flush=True)
            except Exception as exc:
                from gui_agent_bench.failure_detail import native_result

                result, failure = native_result(
                    exc,
                    component='native_driver',
                    correlation_id=work['id'],
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                )
                print(json.dumps({'operation': work['operation'], 'ok': False, 'failure': failure}), flush=True)
            request('/result', {'id': work['id'], 'result': result})


if __name__ == '__main__':
    main()
