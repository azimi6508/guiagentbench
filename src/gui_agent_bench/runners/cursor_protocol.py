"""Bounded Cursor NDJSON capture, with explicit completion and tool restrictions."""

import os
from pathlib import Path
import selectors
import time
from gui_agent_bench.failures import Failure
from gui_agent_bench.io import dump, strict_json


def capture(process, folder, budget, *, catalog_only=False):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
    selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
    buffers = {'stdout': b'', 'stderr': b''}
    used = 0
    terminal = initialized = exited = False
    calls = {}
    started = time.monotonic()
    result = None
    with (folder / 'cursor.ndjson').open('xb') as stdout, (folder / 'cursor-stderr.log').open('xb') as stderr:
        try:
            while not exited:
                if time.monotonic() - started >= budget['timeout_seconds']:
                    raise Failure('action_timeout')
                ready = selector.select(0.2)
                if not ready and process.poll() is not None:
                    raise Failure('incomplete_trajectory')
                for key, _ in ready:
                    channel = key.data
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        if channel == 'stdout' and not terminal:
                            raise Failure('incomplete_trajectory')
                        continue
                    used += len(data)
                    if used > budget['evidence_bytes']:
                        raise Failure('evidence_overflow')
                    target = stdout if channel == 'stdout' else stderr
                    target.write(data)
                    target.flush()
                    if channel == 'stderr':
                        continue
                    buffers[channel] += data
                    if len(buffers[channel]) > budget['result_frame_bytes']:
                        raise Failure('evidence_overflow')
                    while b'\n' in buffers[channel]:
                        line, buffers[channel] = buffers[channel].split(b'\n', 1)
                        value = strict_json(line)
                        if not isinstance(value, dict):
                            raise Failure('incomplete_trajectory')
                        kind = value.get('type')
                        if kind == 'bench_child_exit':
                            if not terminal or value.get('exit_code') != 0:
                                raise Failure('incomplete_trajectory')
                            exited = True
                            continue
                        if terminal:
                            raise Failure('incomplete_trajectory')
                        if kind == 'system' and value.get('subtype') == 'init':
                            if initialized:
                                raise Failure('incomplete_trajectory')
                            initialized = True
                        elif kind == 'tool_call':
                            # Timing/correlation fields sit beside the actual
                            # ToolCall oneof in the pinned client's live events.
                            tool = {
                                k: v
                                for k, v in value.get('tool_call', {}).items()
                                if k not in {'hookAdditionalContexts', 'toolCallId', 'startedAtMs', 'completedAtMs'}
                            }
                            if len(tool) != 1:
                                raise Failure('incomplete_trajectory')
                            if next(iter(tool)) not in {'mcpToolCall', 'getMcpToolsToolCall'}:
                                raise Failure('policy_violation')
                            call_id = value.get('call_id')
                            if not isinstance(call_id, str):
                                raise Failure('incomplete_trajectory')
                            if value.get('subtype') == 'started':
                                if call_id in calls or len(calls) >= budget['observed_tool_items']:
                                    raise Failure('evidence_overflow')
                                calls[call_id] = False
                            elif value.get('subtype') == 'completed':
                                if call_id not in calls or calls[call_id]:
                                    raise Failure('incomplete_trajectory')
                                calls[call_id] = True
                            else:
                                raise Failure('incomplete_trajectory')
                        elif kind == 'result':
                            if (
                                not initialized
                                or value.get('is_error') is not False
                                or value.get('subtype') != 'success'
                                or not all(calls.values())
                            ):
                                raise Failure('incomplete_trajectory')
                            terminal, result = True, value
                        elif (
                            kind == 'connection'
                            and initialized
                            and value.get('subtype') == 'reconnecting'
                            and type(value.get('attempt')) is int
                            and value['attempt'] == 1
                            and value.get('endpoint_url') == 'http://provider:8080'
                        ):
                            # The client has lost its stream. Do not admit its
                            # automatic reconnection, replay inference, or turn
                            # this into a model-answer/protocol-format failure.
                            # The raw event is already persisted above.
                            raise Failure('provider_transport_error')
                        elif kind not in {'user', 'assistant', 'thinking'}:
                            raise Failure('incomplete_trajectory')
            if buffers['stdout']:
                raise Failure('incomplete_trajectory')
        finally:
            selector.close()
    summary = dict(
        runner='cursor',
        completed=True,
        terminal_event=True,
        elapsed_seconds=time.monotonic() - started,
        observed_tool_items=len(calls),
        evidence_bytes=used,
        usage=None,
        provider_cost_usd=None,
        billing_mode='cursor_account',
        result=result,
    )
    dump(folder / 'summary.json', summary)
    return summary
