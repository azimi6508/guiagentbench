"""Bounded stdio app-server driver for the vendored 0.162.0 protocol."""

import base64
import json
import os
from pathlib import Path
import queue
import re
import threading
import time

from gui_agent_bench.failures import Failure
from gui_agent_bench.io import strict_json
from gui_agent_bench.codex_diagnostics import Usage, error_cause
from .registry import canonical

PROMPT = (
    'This is an unattended evaluation. Complete /workspace/instruction.md independently.\n'
    'Paths under /workspace are accessed through the bench tools.\n'
    'Use only tools in the mcp__bench namespace. The pinned client also lists '
    'list_mcp_resources, list_mcp_resource_templates and read_mcp_resource, but this '
    'benchmark provides no resources/templates and those helpers are forbidden. '
    'Do not call them; inspect public files with bench_list_files/bench_read_file/bench_read_image.\n'
    'All permitted evidence is available; choose what to inspect.\n'
    'No follow-up user response will arrive. Save the requested submission.'
)
FIELDS = {
    'initialize': {'clientInfo', 'capabilities'},
    'config/read': {'cwd', 'includeLayers'},
    'configRequirements/read': set(),
    'hooks/list': {'cwds'},
    'account/read': {'refreshToken'},
    'model/list': {'cursor'},
    'thread/start': {
        'model',
        'modelProvider',
        'cwd',
        'approvalPolicy',
        'approvalsReviewer',
        'permissions',
        'ephemeral',
        'allowProviderModelFallback',
    },
    'mcpServerStatus/list': {'threadId', 'serverName', 'cursor'},
    'turn/start': {'threadId', 'permissions', 'approvalPolicy', 'approvalsReviewer', 'model', 'effort', 'input'},
    'turn/interrupt': {'threadId', 'turnId'},
    'thread/read': {'threadId', 'includeTurns'},
}
PARAM_SCHEMAS = {
    'initialize': 'v1/InitializeParams.json',
    'config/read': 'v2/ConfigReadParams.json',
    'hooks/list': 'v2/HooksListParams.json',
    'account/read': 'v2/GetAccountParams.json',
    'model/list': 'v2/ModelListParams.json',
    'thread/start': 'v2/ThreadStartParams.json',
    'mcpServerStatus/list': 'v2/ListMcpServerStatusParams.json',
    'turn/start': 'v2/TurnStartParams.json',
    'turn/interrupt': 'v2/TurnInterruptParams.json',
    'thread/read': 'v2/ThreadReadParams.json',
}


def validate_request(method, params):
    if method not in FIELDS or (params is not None and (not isinstance(params, dict) or set(params) - FIELDS[method])):
        raise Failure('capability_unavailable')
    if method == 'configRequirements/read':
        if params is not None:
            raise Failure('capability_unavailable')
        return
    from jsonschema import Draft7Validator

    schema_root = Path(__file__).resolve().parents[3] / 'configs/codex/schema/0.162.0'
    schema = json.loads((schema_root / PARAM_SCHEMAS[method]).read_text())
    if next(Draft7Validator(schema).iter_errors(params), None) is not None:
        raise Failure('capability_unavailable')


REQUEST_REPLIES = {
    'item/commandExecution/requestApproval': {'decision': 'decline'},
    'item/fileChange/requestApproval': {'decision': 'decline'},
    'item/permissions/requestApproval': {'permissions': {}, 'scope': 'turn'},
    'mcpServer/elicitation/request': {'action': 'decline'},
    'item/tool/requestUserInput': {'answers': {}},
    'execCommandApproval': {'decision': 'abort'},
    'applyPatchApproval': {'decision': 'abort'},
}
BENIGN = {
    'thread/status/changed',
    'thread/name/updated',
    'mcpServerStatus/updated',
    'item/reasoning/summaryTextDelta',
    'item/reasoning/summaryPartAdded',
    'item/reasoning/textDelta',
    'item/mcpToolCall/progress',
    'account/rateLimits/updated',
    'serverRequest/resolved',
}
EXPECTED_FEATURE_NOTICE = (
    'Under-development features enabled: skip_host_skill_discovery. '
    'Under-development features are incomplete and may behave unpredictably. '
    'To suppress this warning, set `suppress_unstable_features_warning = true` in /run/codex/config.toml.'
)


class Driver:
    def __init__(self, process, log, budget, *, secrets=()):
        self.process, self.log, self.budget = process, Path(log), budget
        self.log.mkdir(parents=True, exist_ok=True)
        self.queue = queue.Queue(maxsize=128)
        self.started = time.monotonic()
        self.sequence = self.request_id = self.recorded_bytes = 0
        self.pending = {}
        self.responses = {}
        self.thread_id = self.turn_id = None
        self.items, self.hooks = {}, {}
        self.completed = False
        self.usage = Usage()
        self.tool_items = 0
        self.secrets = tuple(s.encode() if isinstance(s, str) else s for s in secrets if s)
        self.eof = set()
        self.stop = threading.Event()
        self.readers = []
        for stream, name in [(process.stdout, 'stdout'), (process.stderr, 'stderr')]:
            thread = threading.Thread(target=self._read, args=(stream, name), daemon=True)
            thread.start()
            self.readers.append(thread)

    def _read(self, stream, name):
        try:
            while not self.stop.is_set():
                data = os.read(stream.fileno(), 65536)
                while not self.stop.is_set():
                    try:
                        self.queue.put((name, data), timeout=0.1)
                        break
                    except queue.Full:
                        pass
                if not data:
                    return
        except (OSError, ValueError):
            self.queue.put((name, b''))

    def _write_log(self, path, data):
        if any(secret in data for secret in self.secrets):
            marker = canonical({'incomplete': True, 'reason': 'credential_redacted'}) + b'\n'
            with (self.log / path).open('ab') as stream:
                stream.write(marker)
            raise Failure('incomplete_trajectory')
        if self.recorded_bytes + len(data) > self.budget['evidence_bytes']:
            raise Failure('evidence_overflow')
        with (self.log / path).open('ab') as stream:
            stream.write(data)
        self.recorded_bytes += len(data)

    def record(self, direction, raw, envelope, *, private=False):
        if not private and any(secret in raw for secret in self.secrets):
            self._write_log(
                'codex-rpc.ndjson', canonical({'incomplete': True, 'reason': 'credential_redacted'}) + b'\n'
            )
            raise Failure('incomplete_trajectory')
        self.sequence += 1
        record = dict(sequence=self.sequence, direction=direction, monotonic_offset=time.monotonic() - self.started)
        if private:
            record.update(
                privacy_projection=True, id=envelope.get('id'), status='error' if 'error' in envelope else 'received'
            )
        else:
            record.update(frame_base64=base64.b64encode(raw).decode())
        self._write_log('codex-rpc.ndjson', canonical(record) + b'\n')
        return self.sequence

    def send(self, value):
        raw = canonical(value) + b'\n'
        self.record('out', raw, value)
        self.process.stdin.write(raw)
        self.process.stdin.flush()

    def request(self, method, params, deadline):
        validate_request(method, params)
        self.request_id += 1
        identifier = self.request_id
        self.pending[identifier] = method
        self.send(dict(id=identifier, method=method, params=params))
        while identifier not in self.responses:
            self.pump(deadline)
        result = self.responses.pop(identifier)
        if 'error' in result:
            raise Failure('capability_unavailable' if self.turn_id is None else 'provider_error')
        return result['result']

    def normalized(self, kind, params, raw_ref):
        # Raw records own actual text/media; normalized records are references.
        value = dict(
            schema='codex-event-v1',
            sequence=self.sequence,
            runner='codex',
            kind=kind,
            thread_id=params.get('threadId', self.thread_id),
            turn_id=params.get('turnId', self.turn_id),
            raw_refs=[raw_ref],
        )
        item = params.get('item', {})
        if item:
            value.update(item_id=item.get('id'), item_type=item.get('type'))
        self._write_log('normalized.ndjson', canonical(value) + b'\n')

    def event(self, value, raw_ref):
        method, params = value.get('method'), value.get('params') or {}
        if not isinstance(params, dict):
            raise Failure('incomplete_trajectory')
        if 'id' in value:
            reply = REQUEST_REPLIES.get(method)
            self.send(
                {'id': value['id'], 'result': reply}
                if reply is not None
                else {'id': value['id'], 'error': {'code': -32601, 'message': 'Method unavailable'}}
            )
            raise Failure('capability_unavailable')
        if self.thread_id and params.get('threadId', self.thread_id) != self.thread_id:
            raise Failure('incomplete_trajectory')
        if self.turn_id and params.get('turnId') not in {None, self.turn_id}:
            raise Failure('incomplete_trajectory')
        self.normalized(method, params, raw_ref)
        if method == 'configWarning':
            raise Failure('capability_unavailable')
        if method == 'warning':
            if params.get('message') != EXPECTED_FEATURE_NOTICE:
                raise Failure('capability_unavailable')
            return  # Retained in raw/normalized evidence; only this pinned notice.
        if method == 'mcpServer/startupStatus/updated':
            if (
                params.get('name') != 'bench'
                or params.get('status') not in {'starting', 'ready'}
                or params.get('error')
                or params.get('failureReason')
            ):
                raise Failure('capability_unavailable')
            return
        if method == 'remoteControl/status/changed':
            if params.get('status') != 'disabled':
                raise Failure('capability_unavailable')
            return
        if method == 'account/updated':
            if params.get('authMode') != 'chatgpt' or set(params) - {'authMode', 'planType'}:
                raise Failure('capability_unavailable')
            return
        if method in {'model/rerouted', 'thread/compacted'}:
            raise Failure('context_overflow' if method == 'thread/compacted' else 'capability_unavailable')
        if method == 'error':
            error = params.get('error', {})
            raise Failure(error_cause(error.get('codexErrorInfo')))
        if method == 'thread/started':
            identifier = params['thread']['id']
            if self.thread_id not in {None, identifier}:
                raise Failure('incomplete_trajectory')
            self.thread_id = identifier
        elif method in {'turn/started', 'turn/completed'}:
            turn = params['turn']
            if self.turn_id not in {None, turn['id']}:
                raise Failure('incomplete_trajectory')
            self.turn_id = turn['id']
            if method == 'turn/completed':
                if turn.get('status') != 'completed' or turn.get('error') is not None:
                    raise Failure(error_cause((turn.get('error') or {}).get('codexErrorInfo')))
                if any(v['status'] != 'completed' for v in self.items.values()) or any(
                    v != 'completed' for v in self.hooks.values()
                ):
                    raise Failure('incomplete_trajectory')
                self.completed = True
        elif method in {'item/started', 'item/completed'}:
            item = params['item']
            kind, identifier = item['type'], item['id']
            if kind == 'contextCompaction':
                raise Failure('context_overflow')
            if kind not in {'userMessage', 'agentMessage', 'reasoning', 'mcpToolCall'}:
                raise Failure('capability_unavailable')
            previous = self.items.get(identifier)
            if method == 'item/started':
                if previous:
                    raise Failure('incomplete_trajectory')
                if kind == 'mcpToolCall':
                    self.tool_items += 1
                    if self.tool_items > self.budget['observed_tool_items']:
                        raise Failure('budget_exhausted')
            elif not previous or previous['status'] == 'completed':
                raise Failure('incomplete_trajectory')
            self.items[identifier] = dict(
                status='completed' if method.endswith('completed') else 'started', item=item, raw_ref=raw_ref
            )
        elif method in {'hook/started', 'hook/completed'}:
            run = params['run']
            if run['eventName'] in {'preCompact', 'postCompact'}:
                raise Failure('context_overflow')
            if run['eventName'] != 'preToolUse' or run.get('source') not in {'system', 'legacyManagedConfigFile'}:
                raise Failure('capability_unavailable')
            if method.endswith('completed') and run['status'] != 'completed':
                if (
                    run['status'] == 'blocked'
                    and run.get('sourcePath') == '/opt/bench/hooks'
                    and any(
                        entry.get('kind') == 'feedback'
                        and re.fullmatch(
                            r'bench-hook-v1: tool_denied:[A-Za-z_][A-Za-z_0-9:.-]{0,127}', entry.get('text', '')
                        )
                        for entry in run.get('entries', [])
                    )
                ):
                    raise Failure('policy_violation')
                raise Failure('capability_unavailable')
            self.hooks[run['id']] = 'completed' if method.endswith('completed') else 'started'
        elif method == 'thread/tokenUsage/updated':
            self.usage.update(params['tokenUsage'])
        elif method == 'turn/moderationMetadata':
            # This opaque, informational notification is in the pinned schema.
            # Retain its full raw evidence without treating it as a tool result,
            # a policy decision, or proof that the turn completed.
            if (
                set(params) != {'threadId', 'turnId', 'metadata'}
                or not self.thread_id
                or not self.turn_id
                or not isinstance(params['threadId'], str)
                or not isinstance(params['turnId'], str)
            ):
                raise Failure('incomplete_trajectory')
        elif method == 'item/agentMessage/delta':
            if not isinstance(params.get('delta'), str):
                raise Failure('incomplete_trajectory')
        elif method not in BENIGN:
            raise Failure('incomplete_trajectory')

    def pump(self, deadline):
        if not hasattr(self, 'tail'):
            self.tail = b''
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Failure('execution_timeout')
        try:
            name, data = self.queue.get(timeout=min(remaining, 0.25))
        except queue.Empty:
            if self.process.poll() is not None:
                raise Failure('process_error')
            return
        if not data:
            self.eof.add(name)
        if name == 'stderr':
            self.stderr_tail = getattr(self, 'stderr_tail', b'') + data
            if len(self.stderr_tail) > 1_048_576:
                raise Failure('evidence_overflow')
            while b'\n' in self.stderr_tail:
                line, self.stderr_tail = self.stderr_tail.split(b'\n', 1)
                self._write_log('codex-stderr.log', line + b'\n')
            if not data and self.stderr_tail:
                self._write_log('codex-stderr.log', self.stderr_tail)
                self.stderr_tail = b''
            return
        if not data:
            if self.completed and not self.tail:
                return
            if self.tail:
                self._write_log(
                    'codex-rpc.ndjson',
                    canonical({'incomplete': True, 'tail_base64': base64.b64encode(self.tail).decode()}) + b'\n',
                )
            raise Failure('process_error' if not self.tail else 'incomplete_trajectory')
        self.tail += data
        if len(self.tail) > 8_000_000 and b'\n' not in self.tail:
            raise Failure('evidence_overflow')
        while b'\n' in self.tail:
            raw, self.tail = self.tail.split(b'\n', 1)
            if len(raw) > 8_000_000:
                raise Failure('evidence_overflow')
            try:
                value = strict_json(raw)
                if not isinstance(value, dict) or 'jsonrpc' in value:
                    raise ValueError()
            except (ValueError, UnicodeError):
                self.record('in', raw + b'\n', {})
                raise Failure('incomplete_trajectory') from None
            method = self.pending.get(value.get('id')) if 'method' not in value else None
            private = (
                method in {'account/read', 'config/read', 'configRequirements/read'}
                or value.get('method') == 'account/updated'
            )
            ref = self.record('in', raw + b'\n', value, private=private)
            if 'method' not in value:
                identifier = value.get('id')
                if (
                    type(identifier) is not int
                    or identifier not in self.pending
                    or ('result' in value) == ('error' in value)
                ):
                    raise Failure('incomplete_trajectory')
                self.pending.pop(identifier)
                self.responses[identifier] = value
            else:
                self.event(value, ref)

    def turn(self, model, effort, timeout, *, instruction=None):
        deadline = time.monotonic() + timeout
        prompt = PROMPT
        if instruction is not None:
            if not isinstance(instruction, str) or len(instruction.encode()) > 65_536:
                raise Failure('evidence_overflow')
            prompt += '\n\nComplete public /workspace/instruction.md:\n' + instruction
        result = self.request(
            'turn/start',
            dict(
                threadId=self.thread_id,
                permissions='bench',
                approvalPolicy='never',
                approvalsReviewer='user',
                model=model,
                effort=effort,
                input=[{'type': 'text', 'text': prompt, 'text_elements': []}],
            ),
            deadline,
        )
        identifier = result['turn']['id']
        if self.turn_id not in {None, identifier}:
            raise Failure('incomplete_trajectory')
        self.turn_id = identifier
        while not self.completed:
            self.pump(deadline)
        if self.pending or self.tail:
            raise Failure('incomplete_trajectory')

    def interrupt(self):
        if self.thread_id and self.turn_id and not self.completed:
            try:
                self.request(
                    'turn/interrupt', {'threadId': self.thread_id, 'turnId': self.turn_id}, time.monotonic() + 5
                )
            except Exception:
                pass

    def drain(self, seconds=5):
        deadline = time.monotonic() + seconds
        while self.eof != {'stdout', 'stderr'}:
            self.pump(deadline)
        if self.tail or self.pending:
            raise Failure('incomplete_trajectory')

    def close(self):
        self.stop.set()
        for reader in self.readers:
            reader.join(timeout=0.5)
