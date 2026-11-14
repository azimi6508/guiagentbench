"""Runner-neutral, readable trajectories built from original agent records.

Codex JSON-RPC frames and OpenCode session parts are projected into one step
list. Every step keeps its source file and line numbers. Nothing is inferred
between recorded events: missing times, tokens or images stay missing, and
recovered OpenCode parts keep their recovery flag.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re

from .evidence import display_value, image_parts, obj

VERSION = 'trajectory-v1'
FAILURE_KEYS = {'cause', 'message'}
SCREEN_META = re.compile(r'Screenshot coordinate metadata: (\{.*?\})\s*$', re.M)
PERMISSION_DUMP = 'The user has specified a rule which prevents you from using this specific tool call'
UNAVAILABLE = re.compile(r"Model tried to call unavailable tool '([^']*)'")
READ_WRAPPER = re.compile(
    r'^<path>(?P<path>.*?)</path>\s*<type>(?P<type>.*?)</type>\s*<content>\n?(?P<body>.*?)</content>\s*$', re.S
)
NUMBERED = re.compile(r'^(\d+): ?(.*)$')

CATEGORIES = {
    'gui_observe': 'observe',
    'bench_read_image': 'observe',
    'gui_dump_ui': 'inspect',
    'gui_step': 'act',
    'gui_open_url': 'act',
    'gui_reset': 'act',
    'bench_list_files': 'file',
    'bench_read_file': 'file',
    'bench_write_file': 'file',
    'read': 'file',
    'write': 'file',
    'edit': 'file',
    'list': 'file',
    'glob': 'file',
    'grep': 'file',
    'bash': 'shell',
}


def quote(value, limit=80):
    text = str(value)
    return '“' + (text if len(text) <= limit else text[: limit - 1] + '…') + '”'


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def describe(tool, args):
    """Plain-language title and secondary detail for a recorded tool request."""
    args = obj(args)
    path = args.get('path') or args.get('filePath')
    if tool in {'bench_list_files', 'list'}:
        return 'List workspace files', path
    if tool in {'bench_read_file', 'read'}:
        detail = None
        if number(args.get('offset')) or number(args.get('limit')) or number(args.get('max_bytes')):
            unit = 'line' if tool == 'read' else 'byte'
            parts = []
            if number(args.get('offset')):
                parts.append(f'from {unit} {args["offset"]}')
            if number(args.get('limit')):
                parts.append(f'{args["limit"]} lines')
            if number(args.get('max_bytes')):
                parts.append(f'up to {args["max_bytes"]} bytes')
            detail = ', '.join(parts)
        return f'Read {path or "file"}', detail
    if tool == 'bench_read_image':
        return f'View image {path or ""}'.strip(), None
    if tool in {'bench_write_file', 'write'}:
        content = args.get('content')
        lines = (
            content.count('\n') + (0 if content.endswith('\n') else 1) if isinstance(content, str) and content else 0
        )
        return f'Write {path or "file"}', f'{lines} lines' if lines else None
    if tool == 'edit':
        return f'Edit {path or "file"}', None
    if tool == 'gui_observe':
        reference = args.get('reference')
        return 'Take screenshot', f'saved as reference {quote(reference)}' if reference else None
    if tool == 'gui_dump_ui':
        return 'Read UI structure', None
    if tool == 'gui_reset':
        return 'Reset app to its initial state', None
    if tool == 'gui_open_url':
        return f'Open {args.get("url", "URL")}', None
    if tool == 'bash':
        return 'Run shell command', args.get('command')
    if tool == 'gui_step':
        return describe_step(args)
    return (tool or 'Tool call').replace('_', ' ').capitalize(), None


def describe_step(args):
    action = str(args.get('action', 'step'))
    target = None
    if args.get('role') or args.get('name'):
        target = ' '.join(filter(None, [str(args.get('role') or ''), quote(args['name']) if args.get('name') else '']))
    point = f'({args["x"]}, {args["y"]})' if number(args.get('x')) and number(args.get('y')) else None
    if action in {'click', 'tap', 'double_click', 'long_press', 'hover'}:
        verb = {
            'click': 'Click',
            'tap': 'Tap',
            'double_click': 'Double-click',
            'long_press': 'Long-press',
            'hover': 'Hover',
        }[action]
        where = target or (f'at {point}' if point else '')
        return f'{verb} {where}'.strip(), None
    if action in {'type', 'type_text'}:
        return f'Type {quote(args.get("text", ""))}', target
    if action == 'fill':
        return f'Fill {target or "field"} with {quote(args.get("text", args.get("value", "")))}', None
    if action in {'press', 'key'}:
        return f'Press {args.get("key", args.get("text", "key"))}', target
    if action == 'scroll':
        delta = f'by ({args.get("dx", 0)}, {args.get("dy", 0)})'
        return f'Scroll {delta}', f'at {point}' if point else None
    if action in {'drag', 'swipe'}:
        start = f'({args.get("x")}, {args.get("y")})' if point else ''
        end = (
            f'({args["to_x"]}, {args["to_y"]})'
            if number(args.get('to_x')) and number(args.get('to_y'))
            else f'by ({args.get("dx", 0)}, {args.get("dy", 0)})'
        )
        return f'{action.capitalize()} {start} → {end}'.replace('  ', ' '), None
    if action == 'reload':
        return 'Reload', None
    if action == 'evaluate':
        return 'Evaluate script', args.get('code')
    return action.replace('_', ' ').capitalize(), target or (f'at {point}' if point else None)


def point_of(tool, args):
    args = obj(args)
    if tool == 'gui_step' and number(args.get('x')) and number(args.get('y')):
        return [args['x'], args['y']]
    return None


def parse_failure(text):
    """Recognize structured failure-v1 tool errors without rewriting them."""
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if stripped.startswith('{'):
        try:
            value = json.loads(stripped)
        except ValueError:
            value = None
        if isinstance(value, dict) and FAILURE_KEYS <= set(value):
            return {'cause': value.get('cause'), 'message': value.get('message'), 'raw': text}
    if PERMISSION_DUMP in stripped:
        return {'cause': 'permission_rule', 'message': 'Blocked by the runner permission rules.', 'raw': text}
    match = UNAVAILABLE.search(stripped)
    if match:
        return {'cause': 'unavailable_tool', 'message': 'The requested tool is not available in this arm.', 'raw': text}
    return {'cause': None, 'message': stripped, 'raw': text}


def screen_notes(text):
    """Split the fixed screenshot coordinate preamble from other returned text."""
    match = SCREEN_META.search(text or '')
    if not match:
        return None, text
    try:
        meta = json.loads(match[1])
    except ValueError:
        return None, text
    return (
        {'width': meta.get('width'), 'height': meta.get('height'), 'coordinate_space': meta.get('coordinate_space')},
        None,
    )


def read_wrapper(text):
    match = READ_WRAPPER.match(text or '')
    if not match:
        return None
    lines, numbers, note = [], [], []
    for raw in match['body'].split('\n'):
        numbered = NUMBERED.match(raw)
        if numbered and (not numbers or int(numbered[1]) == numbers[-1] + 1):
            numbers.append(int(numbered[1]))
            lines.append(numbered[2])
        elif raw.strip():
            note.append(raw.strip().strip('()'))
    return {
        'path': match['path'],
        'content': '\n'.join(lines),
        'first_line': numbers[0] if numbers else None,
        'last_line': numbers[-1] if numbers else None,
        'note': ' '.join(note) or None,
        'type': match['type'],
    }


def result_view(tool, texts):
    """Readable projection of returned text. Original text stays in `text`."""
    joined = '\n'.join(t for t in texts if isinstance(t, str))
    view = {'kind': 'text' if joined.strip() else 'none', 'text': joined}
    if tool == 'bench_read_file' and joined.strip().startswith('{'):
        try:
            page = json.loads(joined)
            if not isinstance(page, dict) or 'text' not in page:
                return view
            view.update(
                kind='file',
                file={
                    'path': page.get('path'),
                    'content': page.get('text'),
                    'offset': page.get('offset'),
                    'end_offset': page.get('end_offset'),
                    'eof': page.get('eof'),
                    'next_offset': page.get('next_offset'),
                    'sha256': page.get('sha256'),
                },
            )
        except ValueError:
            pass
    elif tool == 'read':
        page = read_wrapper(joined)
        if page:
            view.update(kind='file', file=page)
    elif tool == 'bench_list_files' and joined.strip().startswith('['):
        try:
            view.update(kind='files', files=[f for f in json.loads(joined) if isinstance(f, dict)])
        except ValueError:
            pass
    elif tool == 'bench_write_file' and joined.strip().startswith('{'):
        try:
            page = json.loads(joined)
            if isinstance(page, dict) and 'bytes' in page:
                view.update(kind='write', write=page)
        except ValueError:
            pass
    elif tool == 'gui_dump_ui':
        view['kind'] = 'ui_tree'
    elif tool in {'gui_observe', 'bench_read_image'}:
        meta, rest = screen_notes(joined)
        if meta:
            view.update(kind='screenshot', screen=meta, text=rest or '', notes=joined)
    elif joined.strip() == 'Action completed.':
        view['kind'] = 'ack'
    return view


def png_size(data):
    if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
        return int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
    return None, None


class Builder:
    def __init__(self, runner, source):
        self.runner, self.source = runner, source
        self.steps, self.warnings, self.usage = [], [], []
        self.start_ms = None
        self.info = {}

    def add(self, kind, line, **values):
        step = {
            'id': f's{len(self.steps) + 1}',
            'index': len(self.steps) + 1,
            'kind': kind,
            'source': {'path': self.source, 'lines': [line]},
            'images': [],
            **values,
        }
        self.steps.append(step)
        return step

    def offset(self, ms):
        if not number(ms):
            return None
        if self.start_ms is None:
            self.start_ms = ms
        return ms - self.start_ms

    def finish(self, end, tokens):
        for step in self.steps:
            for key in ('started_ms', 'ended_ms'):
                if number(step.get(key)) and self.start_ms is not None:
                    step[key.replace('_ms', '_offset_ms')] = step[key] - self.start_ms
            if step.get('duration_ms') is None and number(step.get('started_ms')) and number(step.get('ended_ms')):
                step['duration_ms'] = step['ended_ms'] - step['started_ms']
        tools = [s for s in self.steps if s['kind'] == 'tool']
        by_category, by_tool = {}, {}
        for s in tools:
            by_category[s.get('category', 'other')] = by_category.get(s.get('category', 'other'), 0) + 1
            by_tool[s.get('tool')] = by_tool.get(s.get('tool'), 0) + 1
        times = [t for s in self.steps for t in (s.get('started_ms'), s.get('ended_ms')) if number(t)]
        messages = [s for s in self.steps if s['kind'] == 'message']
        final = next(
            (s for s in reversed(messages) if s.get('phase') == 'final_answer'), messages[-1] if messages else None
        )
        stats = {
            'steps': len(self.steps),
            'tool_calls': len(tools),
            'by_category': by_category,
            'by_tool': by_tool,
            'failed_tools': sum(s.get('status') in {'error', 'denied'} for s in tools),
            'blocked': sum(s['kind'] == 'blocked' for s in self.steps),
            'messages': len(messages),
            'screenshots': sum(len(s['images']) for s in self.steps),
            'duration_ms': (max(times) - min(times)) if times else None,
            'tokens': tokens,
            'final_message': final.get('text') if final else None,
        }
        return {
            'version': VERSION,
            'runner': self.runner,
            'source': self.source,
            'info': self.info,
            'start_ms': self.start_ms,
            'steps': self.steps,
            'stats': stats,
            'end': end,
            'usage_series': self.usage,
            'warnings': self.warnings,
        }


def codex(index, run_id, prefix, paths):
    source = prefix + 'logs/agent/codex-rpc.ndjson'
    out = Builder('codex', source)
    bridge = {}
    bridge_path = prefix + 'logs/bridge/bridge.ndjson'
    if bridge_path in paths:
        for line, _, event, _ in index.records(run_id, bridge_path):
            if event.get('phase') == 'completed' and event.get('bridge_call_id'):
                bridge[event['bridge_call_id']] = (line, event)
    items, end, tokens, interrupted = {}, None, None, None
    clock = None  # wall-clock minus monotonic offset, from the latest inbound timestamped frame
    for line, _, event, error in index.records(run_id, source):
        if error:
            out.add('notice', line, level='warning', title='Incomplete or unreadable record', detail=error, minor=False)
            continue
        method = event.get('method')
        params = obj(event.get('params'))
        rpc = obj(event.get('_rpc'))
        emitted = event.get('emittedAtMs')
        monotonic = rpc.get('monotonic_offset')
        if number(emitted) and number(monotonic):
            clock = emitted - monotonic * 1000
        elif emitted is None and number(monotonic) and clock is not None:
            emitted = round(clock + monotonic * 1000)
        if method in {'privacy_projection', None}:
            continue
        if method == 'incomplete_evidence':
            out.add('notice', line, level='warning', title='Incomplete Codex frame', minor=False)
            continue
        if method == 'thread/started':
            thread = obj(params.get('thread'))
            out.info.update(
                model=thread.get('model'),
                reasoning_effort=thread.get('reasoningEffort'),
                cli_version=thread.get('cliVersion'),
                provider=thread.get('modelProvider'),
            )
            continue
        if method == 'turn/started':
            out.offset(emitted)
            continue
        if method in {'item/started', 'item/completed'}:
            item = obj(params.get('item'))
            identifier = item.get('id')
            step = items.get(identifier)
            ms = params.get('startedAtMs') if method == 'item/started' else params.get('completedAtMs')
            ms = ms if number(ms) else emitted
            out.offset(ms)
            if step is None:
                step = codex_item(out, item, line)
                if step is None:
                    continue
                items[identifier] = step
                step['started_ms'] = ms
            else:
                step['source']['lines'].append(line)
            if method == 'item/completed':
                step['ended_ms'] = ms
                codex_complete(index, run_id, prefix, paths, step, item, line, bridge)
            continue
        if method == 'item/agentMessage/delta':
            step = items.get(params.get('itemId'))
            if step is not None and step.get('status') == 'running':
                step['text'] = (step.get('text') or '') + display_value(str(params.get('delta', '')))
            continue
        if method == 'hook/completed':
            run = obj(params.get('run'))
            status = run.get('status')
            feedback = ' '.join(
                str(e.get('text')) for e in run.get('entries') or [] if isinstance(e, dict) and e.get('text')
            )
            call = str(run.get('id', '')).rsplit(':', 1)[-1]
            if run.get('eventName') == 'preToolUse' and status in {'blocked', 'failed'}:
                out.add(
                    'blocked',
                    line,
                    actor='runner',
                    status=status,
                    call_id=call,
                    title='Tool call blocked by policy hook' if status == 'blocked' else 'Policy hook failed',
                    detail=feedback or None,
                    started_ms=emitted,
                    ended_ms=emitted,
                )
                out.offset(emitted)
            elif run.get('eventName') == 'preCompact' and status in {'stopped', 'blocked'}:
                out.add(
                    'notice',
                    line,
                    level='warning',
                    actor='runner',
                    title='Context compaction stopped by the harness',
                    detail=feedback or None,
                    started_ms=emitted,
                    minor=False,
                )
            continue
        if method == 'turn/interrupt' and rpc.get('direction') == 'out':
            interrupted = out.add(
                'interrupt',
                line,
                actor='harness',
                status='error',
                title='Harness interrupted the turn',
                started_ms=emitted,
                time_basis='monotonic offset aligned to the preceding frame' if emitted else None,
            )
            continue
        if method == 'error':
            failure = obj(params.get('error'))
            out.add(
                'error',
                line,
                actor='runner',
                status='error',
                title='Model stream error',
                detail=failure.get('message'),
                code=failure.get('codexErrorInfo'),
                will_retry=params.get('willRetry'),
                started_ms=emitted,
            )
            out.offset(emitted)
            continue
        if method == 'model/rerouted':
            out.add(
                'notice',
                line,
                level='warning',
                actor='runner',
                title='Model rerouted',
                detail=json.dumps(display_value(params), ensure_ascii=False),
                started_ms=emitted,
                minor=False,
            )
            continue
        if method == 'thread/tokenUsage/updated':
            usage = obj(params.get('tokenUsage'))
            total, last = obj(usage.get('total')), obj(usage.get('last'))
            tokens = {
                'input': total.get('inputTokens'),
                'cached_input': total.get('cachedInputTokens'),
                'output': total.get('outputTokens'),
                'reasoning': total.get('reasoningOutputTokens'),
                'total': total.get('totalTokens'),
                'context_window': usage.get('modelContextWindow'),
            }
            out.usage.append(
                {
                    'offset_ms': out.offset(emitted),
                    'line': line,
                    'last_input': last.get('inputTokens'),
                    'last_output': last.get('outputTokens'),
                    'total': total.get('totalTokens'),
                }
            )
            continue
        if method == 'turn/completed':
            turn = obj(params.get('turn'))
            end = {
                'status': turn.get('status'),
                'duration_ms': turn.get('durationMs'),
                'error': display_value(turn.get('error')),
                'line': line,
            }
            out.add(
                'end',
                line,
                actor='runner',
                status='ok' if turn.get('status') == 'completed' else 'error',
                title=f'Turn {turn.get("status", "ended")}',
                duration_ms=turn.get('durationMs'),
                started_ms=emitted,
            )
            out.offset(emitted)
            continue
        if method == 'warning':
            out.add(
                'notice',
                line,
                level='info',
                actor='runner',
                title='Runner warning',
                detail=params.get('message'),
                started_ms=emitted,
                minor=True,
            )
    for step in items.values():
        if step.get('status') == 'running':
            step['status'] = 'incomplete'
    if end is None:
        end = {
            'status': 'interrupted' if interrupted else 'incomplete',
            'duration_ms': None,
            'error': None,
            'line': None,
        }
        out.warnings.append('No turn completion was recorded.')
    return out.finish(end, tokens)


def codex_item(out, item, line):
    kind = item.get('type')
    if kind == 'userMessage':
        text = '\n'.join(str(c.get('text', '')) for c in item.get('content') or [] if isinstance(c, dict))
        return out.add(
            'prompt',
            line,
            actor='harness',
            title='Instruction sent to the agent',
            text=display_value(text),
            status='ok',
        )
    if kind == 'agentMessage':
        return out.add(
            'message',
            line,
            actor='agent',
            title='Agent message',
            text=display_value(item.get('text') or ''),
            phase=item.get('phase'),
            status='running',
        )
    if kind == 'reasoning':
        return out.add('reasoning', line, actor='agent', title='Reasoning', text=None, status='running')
    if kind == 'mcpToolCall':
        tool = item.get('tool')
        title, detail = describe(tool, item.get('arguments'))
        return out.add(
            'tool',
            line,
            actor='agent',
            tool=tool,
            server=item.get('server'),
            call_id=item.get('id'),
            category=CATEGORIES.get(tool, 'other'),
            title=title,
            detail=detail,
            arguments=display_value(item.get('arguments')),
            point=point_of(tool, item.get('arguments')),
            status='running',
        )
    if not kind:
        return None
    return out.add(
        'tool',
        line,
        actor='agent',
        tool=kind,
        category='other',
        title=kind,
        status='running',
        arguments=display_value({k: v for k, v in item.items() if k not in {'type', 'id'}}),
    )


def codex_complete(index, run_id, prefix, paths, step, item, line, bridge):
    kind = step['kind']
    if kind == 'message':
        step['text'] = display_value(item.get('text') or step.get('text') or '')
        step['phase'] = item.get('phase')
        step['status'] = 'ok'
    elif kind == 'reasoning':
        texts = [
            str(s.get('text', s)) if isinstance(s, dict) else str(s)
            for s in (item.get('summary') or []) + (item.get('content') or [])
        ]
        step['text'] = display_value('\n\n'.join(texts)) or None
        step['hidden'] = not texts
        step['status'] = 'ok'
    elif kind == 'tool':
        result = obj(item.get('result'))
        content = [c for c in result.get('content') or [] if isinstance(c, dict)]
        texts = [display_value(c.get('text')) for c in content if c.get('type') == 'text']
        step['duration_ms'] = item.get('durationMs')
        step['result'] = result_view(step.get('tool'), texts)
        call = obj(result.get('_meta')).get('gui_agent_bench.bridge_call_id')
        record = bridge.get(call)
        bridge_event = record[1] if record else {}
        if record:
            step['bridge'] = {'path': prefix + 'logs/bridge/bridge.ndjson', 'line': record[0], 'call_id': call}
        error = item.get('error')
        failure = None
        if error:
            failure = parse_failure(error if isinstance(error, str) else json.dumps(error))
        elif result.get('isError') or bridge_event.get('denied') or obj(bridge_event.get('result')).get('isError'):
            failure = parse_failure('\n'.join(t for t in texts if isinstance(t, str)))
        if failure:
            step['failure'] = failure
        step['status'] = (
            'denied'
            if bridge_event.get('denied')
            else 'error' if failure or bridge_event.get('operation_failed') or item.get('status') == 'failed' else 'ok'
        )
        screen = obj(step['result'].get('screen'))
        for content_item in content:
            if content_item.get('type') != 'image':
                continue
            data = content_item.get('data')
            sha = content_item.get('sha256')
            size = (None, None)
            if isinstance(data, str):
                try:
                    raw = base64.b64decode(data, validate=True)
                    sha = hashlib.sha256(raw).hexdigest()
                    size = png_size(raw)
                except ValueError:
                    continue
            if not sha:
                continue
            blob = prefix + f'logs/bridge/images/{sha}.png'
            image = {
                'sha256': sha,
                'mime': content_item.get('mimeType', 'image/png'),
                'width': size[0] or screen.get('width'),
                'height': size[1] or screen.get('height'),
            }
            if blob in paths:
                image['artifact'] = blob
            elif isinstance(data, str):
                image['embedded'] = {'path': step['source']['path'], 'line': line}
            else:
                continue
            step['images'].append(image)


def opencode(index, run_id, prefix, paths):
    source = prefix + 'logs/agent/trajectory.ndjson'
    out = Builder('opencode', source)
    parts, order, tokens = {}, [], {}
    finishes = []
    for line, _, event, error in index.records(run_id, source):
        if error:
            out.add('notice', line, level='warning', title='Incomplete or unreadable record', detail=error, minor=False)
            continue
        part = obj(event.get('part'))
        identity = (event.get('sessionID'), part.get('messageID'), part.get('id')) if part.get('id') else None
        if identity is not None and identity in parts:
            entry = parts[identity]
            entry['lines'].append(line)
            entry['event'] = event
            continue
        entry = {'lines': [line], 'event': event}
        if identity is not None:
            parts[identity] = entry
        order.append(entry)
    turn_numbers = {}
    for entry in order:
        event, lines = entry['event'], entry['lines']
        part = obj(event.get('part'))
        kind = part.get('type') or event.get('type')
        message = part.get('messageID')
        if message and message not in turn_numbers:
            turn_numbers[message] = len(turn_numbers) + 1
        turn = turn_numbers.get(message)
        recovered = event.get('source') == 'opencode-session-api'
        state = obj(part.get('state'))
        times = obj(state.get('time')) or obj(part.get('time'))
        started = times.get('start') if number(times.get('start')) else None
        ended = times.get('end') if number(times.get('end')) else None
        if started is None and not recovered and number(event.get('timestamp')):
            started = event['timestamp']
        if not recovered:
            out.offset(started)
        common = {
            'turn': turn,
            'recovered': recovered,
            'started_ms': None if recovered else started,
            'ended_ms': None if recovered else ended,
        }
        if kind in {'step-start', 'step_start'}:
            continue
        if kind in {'step-finish', 'step_finish'}:
            used = obj(part.get('tokens'))
            finishes.append(
                {
                    'turn': turn,
                    'reason': part.get('reason'),
                    'cost': part.get('cost'),
                    'tokens': used,
                    'line': lines[-1],
                }
            )
            for key, value in (
                ('input', used.get('input')),
                ('output', used.get('output')),
                ('reasoning', used.get('reasoning')),
                ('cached_input', obj(used.get('cache')).get('read')),
            ):
                if number(value):
                    tokens[key] = tokens.get(key, 0) + value
            target = next((s for s in reversed(out.steps) if s.get('turn') == turn), None)
            if target is not None:
                target['tokens'] = {
                    'input': used.get('input'),
                    'output': used.get('output'),
                    'reasoning': used.get('reasoning'),
                    'cost': part.get('cost'),
                }
                target['finish_reason'] = part.get('reason')
            out.usage.append(
                {
                    'offset_ms': out.offset(event.get('timestamp')) if not recovered else None,
                    'line': lines[-1],
                    'last_input': used.get('input'),
                    'last_output': used.get('output'),
                    'total': None,
                }
            )
            continue
        if kind == 'text':
            step = out.add(
                'message',
                lines[0],
                actor='agent',
                title='Agent message',
                text=display_value(part.get('text') or ''),
                status='ok',
                **common,
            )
        elif kind == 'reasoning':
            text = display_value(part.get('text')) or None
            step = out.add(
                'reasoning',
                lines[0],
                actor='agent',
                title='Reasoning',
                text=text,
                hidden=not text,
                status='ok',
                **common,
            )
        elif kind == 'tool':
            tool = part.get('tool')
            args = state.get('input')
            title, detail = describe(tool, args)
            status = state.get('status')
            output = state.get('output')
            error_text = state.get('error')
            step = out.add(
                'tool',
                lines[0],
                actor='agent',
                tool=tool,
                call_id=part.get('callID'),
                category=CATEGORIES.get(tool, 'other'),
                title=title,
                detail=detail,
                arguments=display_value(args),
                point=point_of(tool, args),
                result=result_view(tool, [display_value(output)] if isinstance(output, str) else []),
                status={'completed': 'ok', 'error': 'error', 'running': 'incomplete', 'pending': 'incomplete'}.get(
                    status, status or 'incomplete'
                ),
                **common,
            )
            if error_text:
                step['failure'] = parse_failure(error_text if isinstance(error_text, str) else json.dumps(error_text))
                if step['failure'].get('cause') in {'permission_rule', 'policy_violation', 'unavailable_tool'}:
                    step['status'] = 'denied'
            if tool == 'write' and isinstance(obj(args).get('content'), str):
                step['written'] = {'path': obj(args).get('filePath'), 'content': obj(args)['content']}
            if tool == 'edit':
                step['edit'] = {
                    'path': obj(args).get('filePath'),
                    'old': obj(args).get('oldString'),
                    'new': obj(args).get('newString'),
                }
        elif event.get('type') == 'error' or kind == 'error':
            failure = obj(event.get('error'))
            step = out.add(
                'error',
                lines[0],
                actor='runner',
                status='error',
                title='Runner error',
                detail=display_value(
                    obj(failure.get('data')).get('message') or failure.get('name') or json.dumps(display_value(event))
                ),
                **common,
            )
        else:
            step = out.add(
                'notice',
                lines[0],
                level='info',
                actor='runner',
                title=str(kind or 'record').replace('_', ' '),
                minor=True,
                **common,
            )
        step['source']['lines'] = lines
        for sha, mime, data in image_parts(event):
            width, height = png_size(data)
            if not any(i['sha256'] == sha for i in step['images']):
                step['images'].append(
                    {
                        'sha256': sha,
                        'mime': mime,
                        'width': width,
                        'height': height,
                        'embedded': {'path': source, 'line': lines[-1]},
                    }
                )
    last = finishes[-1] if finishes else None
    status = 'completed' if last and last['reason'] == 'stop' else 'incomplete'
    end = {
        'status': status,
        'finish_reason': last['reason'] if last else None,
        'model_steps': len(finishes),
        'line': last['line'] if last else None,
    }
    if status == 'incomplete':
        out.warnings.append('The last recorded model step did not finish with reason "stop".')
    if any(s.get('recovered') for s in out.steps):
        out.warnings.append(
            'Some parts were recovered from the OpenCode session API; their recorded times are recovery times.'
        )
    result = out.finish(end, tokens or None)
    result['stats']['model_steps'] = len(finishes)
    return result


def cursor(index, run_id, prefix, paths):
    source = prefix + 'logs/agent/cursor.ndjson'
    out = Builder('cursor', source)
    bridge = {}
    bridge_path = prefix + 'logs/bridge/bridge.ndjson'
    if bridge_path in paths:
        for line, _, event, _ in index.records(run_id, bridge_path):
            if event.get('phase') == 'completed':
                bridge[event['bridge_call_id']] = (line, event)
    tools = {}
    end = {'status': 'incomplete'}
    for line, _, event, error in index.records(run_id, source):
        if error:
            out.warnings.append('Unreadable Cursor record.')
            continue
        kind = event.get('type')
        clock = event.get('timestamp_ms')
        if number(clock):
            out.offset(clock)
        if kind in {'user', 'assistant', 'thinking'}:
            text = '\n'.join(
                str(c.get('text', '')) for c in obj(event.get('message')).get('content', []) if isinstance(c, dict)
            )
            out.add(
                'prompt' if kind == 'user' else 'reasoning' if kind == 'thinking' else 'message',
                line,
                actor='harness' if kind == 'user' else 'agent',
                title='Instruction' if kind == 'user' else 'Agent message',
                text=display_value(text),
                status='ok',
                started_ms=clock,
            )
        elif kind == 'tool_call':
            call = event.get('call_id')
            tool = obj(event.get('tool_call'))
            mcp = obj(tool.get('mcpToolCall'))
            arguments = obj(mcp.get('args'))
            name = arguments.get('toolName') or arguments.get('name') or next(iter(tool), 'unknown')
            if event.get('subtype') == 'started':
                title, detail = describe(name, arguments.get('args'))
                tools[call] = out.add(
                    'tool',
                    line,
                    actor='agent',
                    tool=name,
                    call_id=call,
                    title=title,
                    detail=detail,
                    category=CATEGORIES.get(name, 'other'),
                    arguments=display_value(arguments.get('args')),
                    status='running',
                    started_ms=clock,
                )
            elif call in tools:
                step = tools[call]
                step['ended_ms'] = clock
                step['source']['lines'].append(line)
                result = obj(mcp.get('result'))
                success = obj(result.get('success'))
                key = obj(success.get('resultMeta')).get('gui_agent_bench.bridge_call_id')
                record = bridge.get(key)
                if record:
                    item = {'result': record[1]['result'], 'status': 'completed'}
                    codex_complete(index, run_id, prefix, paths, step, item, line, bridge)
                else:
                    step['status'] = 'ok' if success else 'error' if result else 'unknown'
                    step['result'] = {'kind': 'text', 'text': display_value(result)}
        elif kind == 'result':
            end = {
                'status': (
                    'completed' if event.get('subtype') == 'success' and not event.get('is_error') else 'incomplete'
                ),
                'line': line,
                'finish_reason': event.get('subtype'),
            }
        elif kind not in {'system'}:
            out.add('notice', line, title=str(kind or 'Unknown event'), detail=display_value(event), level='warning')
    return out.finish(end, None)


def claude(index, run_id, prefix, paths):
    source = prefix + 'logs/agent/claude.ndjson'
    out = Builder('claude', source)
    # Correlate tool results with trusted bridge records by tool name and exact
    # arguments, in order; the client does not echo the bridge correlation ID.
    bridge = []
    bridge_path = prefix + 'logs/bridge/bridge.ndjson'
    if bridge_path in paths:
        for line, _, event, _ in index.records(run_id, bridge_path):
            if event.get('phase') == 'completed':
                bridge.append((line, event))
    used = set()
    tools, raw_arguments = {}, {}
    end = {'status': 'incomplete'}
    tokens = None
    for line, _, event, error in index.records(run_id, source):
        if error:
            out.warnings.append('Unreadable Claude Code record.')
            continue
        kind = event.get('type')
        message = obj(event.get('message'))
        if kind == 'system' and event.get('subtype') == 'init':
            out.info.update(
                model=event.get('model'), tools=event.get('tools'), permission_mode=event.get('permissionMode')
            )
        elif kind == 'assistant':
            for block in message.get('content') or []:
                block = obj(block)
                if block.get('type') == 'text':
                    out.add(
                        'message',
                        line,
                        actor='agent',
                        title='Agent message',
                        text=display_value(block.get('text')),
                        status='ok',
                    )
                elif block.get('type') in {'thinking', 'redacted_thinking'}:
                    text = block.get('thinking')
                    out.add(
                        'reasoning',
                        line,
                        actor='agent',
                        title='Reasoning',
                        text=display_value(text) or None,
                        hidden=not text,
                        status='ok',
                    )
                elif block.get('type') == 'tool_use':
                    name = str(block.get('name') or 'unknown').removeprefix('mcp__bench__')
                    title, detail = describe(name, block.get('input'))
                    raw_arguments[block.get('id')] = block.get('input')
                    tools[block.get('id')] = out.add(
                        'tool',
                        line,
                        actor='agent',
                        tool=name,
                        call_id=block.get('id'),
                        title=title,
                        detail=detail,
                        category=CATEGORIES.get(name, 'other'),
                        arguments=display_value(block.get('input')),
                        status='running',
                    )
        elif kind == 'user':
            for block in message.get('content') or []:
                block = obj(block)
                step = tools.get(block.get('tool_use_id'))
                if block.get('type') != 'tool_result' or step is None:
                    continue
                step['source']['lines'].append(line)
                record = next(
                    (
                        (i, r)
                        for i, r in enumerate(bridge)
                        if i not in used
                        and r[1].get('tool') == step['tool']
                        and r[1].get('arguments') == raw_arguments.get(block.get('tool_use_id'))
                    ),
                    None,
                )
                if record:
                    used.add(record[0])
                    lookup = {record[1][1].get('bridge_call_id'): record[1]}
                    item = {
                        'result': {
                            **obj(record[1][1].get('result')),
                            '_meta': {'gui_agent_bench.bridge_call_id': record[1][1].get('bridge_call_id')},
                        },
                        'status': 'completed',
                    }
                    codex_complete(index, run_id, prefix, paths, step, item, line, lookup)
                else:
                    content = block.get('content')
                    texts = (
                        [display_value(obj(c).get('text')) for c in content if obj(c).get('type') == 'text']
                        if isinstance(content, list)
                        else [display_value(content)]
                    )
                    step['status'] = 'error' if block.get('is_error') else 'ok'
                    step['result'] = result_view(step['tool'], texts)
        elif kind == 'result':
            usage = obj(event.get('usage'))
            counts = [usage.get(k) for k in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')]
            tokens = {
                'input': sum(c for c in counts if isinstance(c, int)) if isinstance(counts[0], int) else None,
                'output': usage.get('output_tokens'),
                'cached_input': usage.get('cache_read_input_tokens'),
                'cache_write': usage.get('cache_creation_input_tokens'),
            }
            completed = event.get('subtype') == 'success' and event.get('is_error') is False
            end = {
                'status': 'completed' if completed else 'incomplete',
                'line': line,
                'finish_reason': event.get('terminal_reason') or event.get('subtype'),
            }
        elif kind in {'rate_limit_event', 'bench_child_exit', 'system'}:
            continue
        else:
            out.add('notice', line, title=str(kind or 'Unknown event'), detail=display_value(event), level='warning')
    return out.finish(end, tokens)


def build(index, run_id, prefix, paths):
    """Return the normalized trajectory for one trial prefix, or None."""
    if prefix + 'logs/agent/codex-rpc.ndjson' in paths:
        return codex(index, run_id, prefix, paths)
    if prefix + 'logs/agent/cursor.ndjson' in paths:
        return cursor(index, run_id, prefix, paths)
    if prefix + 'logs/agent/claude.ndjson' in paths:
        return claude(index, run_id, prefix, paths)
    if prefix + 'logs/agent/trajectory.ndjson' in paths:
        return opencode(index, run_id, prefix, paths)
    return None
