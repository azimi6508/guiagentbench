"""Bounded Claude Code stream-json capture with explicit completion and tool restrictions."""

import os
from pathlib import Path
import selectors
import time
from gui_agent_bench.failures import Failure
from gui_agent_bench.io import dump, strict_json

ADMITTED_RATE_STATUS = {'allowed', 'allowed_warning'}


class Session:
    """Validate one stream-json event at a time; raise on the first deviation."""

    def __init__(self, policy, budget):
        self.policy = policy
        self.budget = budget
        self.allowed = set(policy['tool_names'])
        self.initialized = self.terminal = self.exited = False
        self.calls = {}
        self.assistant_messages = set()
        self.result = None
        self.rate_limits = []

    def event(self, value):
        if not isinstance(value, dict):
            raise Failure('incomplete_trajectory')
        kind = value.get('type')
        if kind == 'bench_child_exit':
            if not self.terminal or value.get('exit_code') != 0:
                raise Failure('incomplete_trajectory')
            self.exited = True
            return
        if self.terminal:
            raise Failure('incomplete_trajectory')
        if kind == 'system':
            self.system(value)
        elif not self.initialized:
            raise Failure('incomplete_trajectory')
        elif kind == 'assistant':
            self.assistant(value)
        elif kind == 'user':
            self.user(value)
        elif kind == 'rate_limit_event':
            info = value.get('rate_limit_info')
            if not isinstance(info, dict):
                raise Failure('incomplete_trajectory')
            self.rate_limits.append({k: info.get(k) for k in ('status', 'isUsingOverage', 'rateLimitType')})
            # Paid overage is never admitted implicitly; a rejected window is a provider limit.
            if info.get('isUsingOverage') is True:
                raise Failure('budget_exhausted')
            if info.get('status') not in ADMITTED_RATE_STATUS:
                raise Failure('provider_rate_limit')
        elif kind == 'result':
            self.finish(value)
        else:
            raise Failure('incomplete_trajectory')

    def system(self, value):
        subtype = value.get('subtype')
        if subtype == 'init':
            servers = value.get('mcp_servers')
            if self.initialized:
                raise Failure('incomplete_trajectory')
            if (
                not isinstance(value.get('tools'), list)
                or set(value['tools']) != self.allowed
                or len(value['tools']) != len(self.allowed)
            ):
                raise Failure('capability_unavailable')
            if (
                not isinstance(servers, list)
                or len(servers) != 1
                or not isinstance(servers[0], dict)
                or servers[0].get('name') != 'bench'
                or servers[0].get('status') != 'connected'
            ):
                raise Failure('capability_unavailable')
            if value.get('model') != self.policy['model'] or value.get('permissionMode') != 'dontAsk':
                raise Failure('policy_violation')
            self.initialized = True
        elif subtype == 'compact_boundary':
            # Compaction would silently replace evidence the model saw.
            raise Failure('context_overflow')
        elif subtype == 'api_retry':
            raise Failure('provider_transport_error')
        elif subtype == 'thinking_tokens':
            # Informational client estimate of streamed thinking; it changes nothing the model sees.
            if (
                not self.initialized
                or set(value) - {'type', 'subtype', 'estimated_tokens', 'estimated_tokens_delta', 'session_id', 'uuid'}
                or any(
                    type(value.get(k)) is not int or value[k] < 0
                    for k in ('estimated_tokens', 'estimated_tokens_delta')
                )
            ):
                raise Failure('incomplete_trajectory')
        else:
            raise Failure('incomplete_trajectory')

    def assistant(self, value):
        message = value.get('message')
        if not isinstance(message, dict) or not isinstance(message.get('content'), list):
            raise Failure('incomplete_trajectory')
        if message.get('model') == '<synthetic>':
            # The client synthesizes this message for API errors; the gateway
            # record carries the authoritative provider cause.
            raise Failure('provider_error')
        if isinstance(message.get('id'), str):
            self.assistant_messages.add(message['id'])
        for block in message['content']:
            if not isinstance(block, dict):
                raise Failure('incomplete_trajectory')
            if block.get('type') in {'tool_use', 'server_tool_use', 'mcp_tool_use'}:
                if block.get('type') != 'tool_use' or block.get('name') not in self.allowed:
                    raise Failure('policy_violation')
                key = block.get('id')
                if not isinstance(key, str) or key in self.calls:
                    raise Failure('incomplete_trajectory')
                if len(self.calls) >= self.budget['observed_tool_items']:
                    raise Failure('budget_exhausted')
                self.calls[key] = False
            elif block.get('type') not in {'text', 'thinking', 'redacted_thinking'}:
                raise Failure('incomplete_trajectory')

    def user(self, value):
        message = value.get('message')
        content = message.get('content') if isinstance(message, dict) else None
        if not isinstance(content, list):
            raise Failure('incomplete_trajectory')
        for block in content:
            if not isinstance(block, dict) or block.get('type') != 'tool_result':
                raise Failure('incomplete_trajectory')
            key = block.get('tool_use_id')
            if key not in self.calls or self.calls[key]:
                raise Failure('incomplete_trajectory')
            self.calls[key] = True

    def finish(self, value):
        if (
            value.get('subtype') != 'success'
            or value.get('is_error') is not False
            or value.get('terminal_reason', 'completed') != 'completed'
            or not all(self.calls.values())
        ):
            raise Failure('incomplete_trajectory')
        self.terminal = True
        self.result = {
            k: value.get(k)
            for k in (
                'subtype',
                'is_error',
                'terminal_reason',
                'num_turns',
                'duration_ms',
                'duration_api_ms',
                'stop_reason',
                'total_cost_usd',
                'usage',
                'modelUsage',
                'permission_denials',
            )
        }
        if self.result.get('permission_denials'):
            raise Failure('policy_violation')


def capture(process, folder, budget, policy):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
    selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
    pending = b''
    used = 0
    started = time.monotonic()
    session = Session(policy, budget)
    with (folder / 'claude.ndjson').open('xb') as stdout, (folder / 'claude-stderr.log').open('xb') as stderr:
        try:
            while not session.exited:
                if time.monotonic() - started >= budget['timeout_seconds']:
                    raise Failure('action_timeout')
                ready = selector.select(0.2)
                if not ready and process.poll() is not None:
                    raise Failure('incomplete_trajectory')
                for key, _ in ready:
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        if key.data == 'stdout' and not session.exited:
                            raise Failure('incomplete_trajectory')
                        continue
                    used += len(data)
                    if used > budget['evidence_bytes']:
                        raise Failure('evidence_overflow')
                    target = stdout if key.data == 'stdout' else stderr
                    target.write(data)
                    target.flush()
                    if key.data == 'stderr':
                        continue
                    pending += data
                    if len(pending) > budget['result_frame_bytes']:
                        raise Failure('evidence_overflow')
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        if line.strip():
                            session.event(strict_json(line))
            if pending.strip():
                raise Failure('incomplete_trajectory')
        finally:
            selector.close()
    usage = (session.result or {}).get('usage') or {}
    summary = dict(
        runner='claude',
        completed=True,
        terminal_event=True,
        elapsed_seconds=time.monotonic() - started,
        observed_tool_items=len(session.calls),
        model_messages=len(session.assistant_messages),
        evidence_bytes=used,
        usage={
            'inputTokens': usage.get('input_tokens'),
            'outputTokens': usage.get('output_tokens'),
            'cacheCreationInputTokens': usage.get('cache_creation_input_tokens'),
            'cacheReadInputTokens': usage.get('cache_read_input_tokens'),
        },
        client_estimated_cost_usd=(session.result or {}).get('total_cost_usd'),
        provider_cost_usd=None,
        rate_limits=session.rate_limits,
        result=session.result,
    )
    dump(folder / 'summary.json', summary)
    return summary
