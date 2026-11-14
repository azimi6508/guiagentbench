"""Fixed Cursor inference reverse proxy. Credentials never enter the agent.

HTTP/1 SSE is selected in the pinned CLI. Only the fixed API's admitted RPC
methods are forwarded, once; bodies and headers never enter operator logs.
"""

import hashlib
import base64
import gzip
import io
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import sys
import threading
import time

BODY_LIMIT = 32_000_000
PRIVACY_PATH = '/aiserver.v1.DashboardService/GetUserPrivacyMode'
# The pinned CLI caches privacy settings for an hour but also samples them on
# routine requests. Coalesce identical reads for at most one minute. Never use
# a stale value after a failed refresh, cache an error, or share across trials.
PRIVACY_CACHE_SECONDS = 60
LOG_LOCK = threading.Lock()
CONNECT_CODES = {
    'canceled',
    'unknown',
    'invalid_argument',
    'deadline_exceeded',
    'not_found',
    'already_exists',
    'permission_denied',
    'resource_exhausted',
    'failed_precondition',
    'aborted',
    'out_of_range',
    'unimplemented',
    'internal',
    'unavailable',
    'data_loss',
    'unauthenticated',
}
CONTRACT_TERMS = (
    'compression',
    'header',
    'body',
    'mcp',
    'tool',
    'schema',
    'json',
    'model',
    'auth',
    'request',
    'conversation',
    'invalid',
    'missing',
    'unsupported',
    'uuid',
    'harness',
    'token',
    'agent',
    'version',
    'large',
    'empty',
    'required',
    'workspace',
    'endpoint',
    'parameter',
    'allowed',
    'name',
    'permission',
    'login',
    'id',
    'exist',
    'found',
    'expired',
    'binary',
    'base64',
    'hex',
    'number',
    'format',
    'response',
    'session',
    'encoding',
    'grpc',
    'connect',
    'message',
    'data',
    'serialize',
    'deserialize',
    'parse',
    'expected',
    'context',
    'prompt',
    'field',
    'limit',
    'key',
    'size',
    'length',
    'bytes',
    'content',
    'string',
    'type',
    'client',
    'not',
    'valid',
    'must',
    'too',
    'one',
    'zero',
    'positive',
    'value',
    'index',
)


def provider_error_summary(error):
    """Only pinned protocol codes; never provider messages or free-form details."""
    code = error.get('code') if isinstance(error, dict) else None
    result = {'code': code if isinstance(code, str) and code in CONNECT_CODES else 'unknown'}
    message = error.get('message') if isinstance(error, dict) else None
    if isinstance(message, str):
        result['contract_terms'] = [term for term in CONTRACT_TERMS if re.search(r'\b' + term + r'\b', message.lower())]
    for detail in error.get('details', []) if isinstance(error, dict) else []:
        if not isinstance(detail, dict) or detail.get('type') != 'aiserver.v1.ErrorDetails':
            continue
        try:
            data = base64.b64decode(detail.get('value', ''), validate=True)
            codes = [v for n, k, v in proto_fields(data) if n == 1 and k == 0]
            if len(codes) == 1 and 0 <= codes[0] <= 128:
                result['cursor_error_number'] = codes[0]
        except (ValueError, TypeError):
            pass
    return result


def record(value):
    # Threaded account/config requests can finish together. Serialize the whole
    # NDJSON line, including its newline, so evidence never interleaves.
    with LOG_LOCK:
        sys.stdout.write(json.dumps(value) + '\n')
        sys.stdout.flush()


RPC = re.compile(
    r'^/(?:aiserver\.v1\.(?:AiService|DashboardService|BidiService|ServerConfigService)|agent\.v1\.AgentService)/[A-Za-z][A-Za-z0-9]*$'
)
# Read-only account/catalog calls and the single agent stream. Additions require
# explicit source changes and requalification, never a permissive path fallback.
METHODS = {
    'GetUsableModels',
    'GetDefaultModel',
    'GetServerConfig',
    'GetUserInfo',
    'GetUserPrivacyMode',
    'GetClientConfig',
    'GetPublicConfig',
    'GetModelDetails',
    'GetCliConfig',
    'GetCliUpdate',
    'GetTeamMemberships',
    'GetTeamUsage',
    'GetAvailableModels',
    'GetModelCatalog',
    'GetFeatureFlags',
    'Run',
    'RunSSE',
    'StreamUnifiedChatWithTools',
    'StreamUnifiedChatWithToolsSSE',
}
METHODS |= {
    'GetDefaultModelForCli',
    'GetAllowedModelIntents',
    'BidiAppend',
    'AvailableModels',
    'GetMe',
    'GetTeamAdminSettingsOrEmptyIfNotInTeam',
    'GetPromptContextUsage',
    'WarmUp',
    'UpdateConversationMetadata',
    'GetNewChatNudgeLegacyModelPicker',
    'GetNewChatNudgeParameterizedModelPicker',
}


def proto_fields(data):
    """Strict bounded wire reader for the pinned dispatch envelope only."""
    position = 0

    def integer():
        nonlocal position
        value = 0
        for shift in range(0, 70, 7):
            if position >= len(data):
                raise ValueError()
            byte = data[position]
            position += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise ValueError()

    fields = []
    while position < len(data):
        tag = integer()
        number, kind = tag >> 3, tag & 7
        if number == 0:
            raise ValueError()
        if kind == 0:
            value = integer()
        elif kind in {1, 2, 5}:
            size = integer() if kind == 2 else 8 if kind == 1 else 4
            if size > len(data) - position:
                raise ValueError()
            value = data[position : position + size]
            position += size
        else:
            raise ValueError()
        fields.append((number, kind, value))
        if len(fields) > 4096:
            raise ValueError()
    return fields


def validate_privacy_response(headers, body):
    """Pinned unary response; never cache HTTP-success RPC errors or bad wire."""
    if headers.get('Content-Type', '').split(';', 1)[0].lower() != 'application/proto' or headers.get(
        'Grpc-Status'
    ) not in {None, '0'}:
        raise ValueError('Privacy RPC did not complete successfully')
    fields = proto_fields(body)
    if len({n for n, _, _ in fields}) != len(fields) or any(
        n not in range(1, 8)
        or kind != 0
        or n in {1, 7}
        and value not in range(5)
        or n in {3, 4, 5, 6}
        and value not in {0, 1}
        for n, kind, value in fields
    ):
        raise ValueError('Unqualified privacy response')


class DispatchDenied(ValueError):
    def __init__(self, reason, fields):
        super().__init__('Server dispatch denied')
        self.summary = {
            'reason': reason,
            'fields': [[n, k, len(v) if isinstance(v, bytes) else None] for n, k, v in fields[:64]],
        }


class RelayDenied(ValueError):
    """Fixed operator reason only; never retain request data or exception text."""

    def __init__(self, reason):
        super().__init__('Cursor relay rejected a request')
        self.reason = reason


def validate_server_frame(data, binary=False):
    """An independent process boundary veto before any native command dispatch."""
    if binary:
        fields = proto_fields(data)
        # TTFT timing is independent metadata in the pinned protobuf, not a
        # dispatch oneof. It may accompany a single actual server message.
        messages = [f for f in fields if f[0] != 8]
        if (
            not fields
            or len(messages) > 1
            or len({n for n, _, _ in fields}) != len(fields)
            or any(n not in {1, 2, 3, 4, 5, 8} or kind != 2 for n, kind, _ in fields)
        ):
            raise DispatchDenied('server_envelope', fields)
        if not messages:
            return
        number, _, payload = messages[0]
        if number == 2:
            dispatch = proto_fields(payload)
            operations = [n for n, _, _ in dispatch if n not in {1, 15, 19, 55, 57}]
            if len(operations) != 1 or operations[0] not in {10, 11, 27, 36, 42}:
                raise DispatchDenied('native_operation', dispatch)
        elif number == 1 and any(n in {9, 10, 11, 24} for n, _, _ in proto_fields(payload)):
            raise DispatchDenied('compaction_or_reroute', proto_fields(payload))
        return
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError()
    if 'execServerMessage' in value:
        message = value['execServerMessage']
        operations = set(message) - {'id', 'execId', 'machineId', 'spanContext', 'acceptHookAdditionalContexts'}
        if len(operations) != 1 or not operations <= {
            'mcpArgs',
            'executeHookArgs',
            'mcpStateExecArgs',
            'mcpAllowlistPrecheckArgs',
            'requestContextArgs',
        }:
            raise ValueError('Native execution denied')
    if 'interactionQuery' in value:
        raise ValueError('External interaction denied')
    update = value.get('interactionUpdate', {})
    if any(k in update for k in ('summary', 'summaryStarted', 'summaryCompleted', 'routedModel')):
        raise ValueError('Context compaction or model rerouting denied')
    if set(value) - {
        'interactionUpdate',
        'execServerMessage',
        'execServerControlMessage',
        'conversationCheckpointUpdate',
        'kvServerMessage',
        'ttftBreakdown',
    }:
        raise ValueError('Unknown server message denied')


def allowed_path(path):
    return bool(RPC.fullmatch(path)) and path.rsplit('/', 1)[-1] in METHODS


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.count = 0
        self.failed = False
        self.streams = set()
        self.stream_started = False
        self.run_started = False
        self.counts = {'payload': 0, 'heartbeat': 0, 'metadata': 0}
        self.catalog = None
        self.privacy_lock = threading.Lock()
        self.privacy_cache = None
        self.privacy_generation = 0

    def admit(self, path, data, selected, category, stream):
        limits = {
            'payload': int(os.environ.get('GAB_CURSOR_PAYLOAD_LIMIT', '2048')),
            'heartbeat': int(os.environ.get('GAB_CURSOR_HEARTBEAT_LIMIT', '2528')),
            'metadata': int(os.environ.get('GAB_CURSOR_METADATA_LIMIT', '2528')),
        }
        signature = (path, hashlib.sha256(data).hexdigest())
        with self.lock:
            if self.failed:
                raise RelayDenied('session_already_failed')
            if self.counts[category] >= limits[category]:
                raise RelayDenied(category + '_request_limit')
            if selected is not None:
                if selected['sha256'] != os.environ['GAB_CURSOR_MODEL_IDENTITY']:
                    raise RelayDenied('model_identity_mismatch')
                if self.run_started:
                    raise RelayDenied('repeated_model_start')
                self.run_started = True
            if stream and self.stream_started:
                raise RelayDenied('repeated_inference_stream')
            if (stream or path.endswith('/BidiAppend')) and signature in self.streams:
                raise RelayDenied('replayed_agent_request')
            if stream or path.endswith('/BidiAppend'):
                self.streams.add(signature)
            if stream:
                self.stream_started = True
            self.count += 1
            self.counts[category] += 1


def append_fields(body, content_type, content_encoding=''):
    """Decode only the pinned client envelope, in memory, with original bounds."""
    if content_encoding == 'gzip':
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            body = stream.read(BODY_LIMIT + 1)
        if len(body) > BODY_LIMIT:
            raise ValueError()
    if 'proto' in content_type:
        outer = proto_fields(body)
        hex_data = next((v for n, k, v in outer if n == 1 and k == 2), None)
        binary = next((v for n, k, v in outer if n == 4 and k == 2), None)
        message = binary if binary is not None else bytes.fromhex(hex_data.decode()) if hex_data else b''
        return proto_fields(message)
    raise RelayDenied('request_encoding')


def request_category(path, body, content_type, content_encoding=''):
    if path.endswith('/BidiAppend'):
        fields = append_fields(body, content_type, content_encoding)
        # Only the exact heartbeat oneof is exempt from payload accounting.
        # Mixed, unknown and empty messages consume the payload allowance.
        if len(fields) == 1 and fields[0][0:2] == (7, 2):
            return 'heartbeat'
        return 'payload'
    if path.rsplit('/', 1)[-1] in {'Run', 'RunSSE', 'StreamUnifiedChatWithTools', 'StreamUnifiedChatWithToolsSSE'}:
        return 'payload'
    return 'metadata'


def requested_identity(body, content_type, content_encoding=''):
    """Bind the resolved model/parameters, excluding provider credentials."""
    if 'proto' in content_type:
        runs = [v for n, k, v in append_fields(body, content_type, content_encoding) if n == 1 and k == 2]
        if not runs:
            return None
        if len(runs) != 1:
            raise ValueError()
        fields = proto_fields(runs[0])
        selected = [v for n, k, v in fields if n == 9 and k == 2]
        requested = bool(selected)
        if not selected:
            selected = [v for n, k, v in fields if n == 3 and k == 2]
        if len(selected) != 1:
            raise ValueError()
        identity = proto_fields(selected[0])
        if any(n in ({4, 5, 6} if requested else {8, 9, 10}) for n, _, _ in identity):
            raise RelayDenied('provider_credentials_in_request')
        ids = [v.decode('utf-8', 'strict') for n, k, v in identity if n == 1 and k == 2]
        if len(ids) != 1:
            raise ValueError()
        wire_sha = hashlib.sha256(selected[0]).hexdigest()
        if requested:
            binding = canonical_requested_model(identity)
            encoded = json.dumps(binding, sort_keys=True, separators=(',', ':')).encode()
            return {
                'model_id': ids[0],
                'sha256': hashlib.sha256(encoded).hexdigest(),
                'schema': 'requested-model-semantic-v1',
                'wire_sha256': wire_sha,
            }
        # A legacy model-details message cannot substitute for requested-model
        # parameters. Keep this distinct and byte-bound until separately qualified.
        return {
            'model_id': ids[0],
            'sha256': wire_sha,
            'schema': 'legacy-model-details-wire-v1',
            'wire_sha256': wire_sha,
        }
    raise RelayDenied('request_encoding')


def canonical_requested_model(fields):
    """Pinned RequestedModel semantics, including every permitted parameter.

    Protobuf field order and parameter-map iteration order are not model identity.
    Unknown fields, duplicate parameter IDs and credentials remain inadmissible.
    """
    if any(n not in {1, 2, 3, 7} or k != (0 if n in {2, 7} else 2) for n, k, _ in fields):
        raise RelayDenied('model_identity_schema')

    def single(number, default):
        values = [v for n, _, v in fields if n == number]
        if len(values) > 1:
            raise RelayDenied('model_identity_duplicate_field')
        return values[0] if values else default

    model = single(1, b'').decode('utf-8', 'strict')
    if not model:
        raise RelayDenied('model_identity_schema')
    maximum, builtin = single(2, 0), single(7, 0)
    if maximum not in {0, 1} or builtin not in {0, 1}:
        raise RelayDenied('model_identity_schema')
    parameters = {}
    for n, _, value in fields:
        if n != 3:
            continue
        parts = proto_fields(value)
        if any(tag not in {1, 2} or kind != 2 for tag, kind, _ in parts):
            raise RelayDenied('model_parameter_schema')
        names = [v for tag, _, v in parts if tag == 1]
        values = [v for tag, _, v in parts if tag == 2]
        if len(names) != 1 or len(values) > 1:
            raise RelayDenied('model_parameter_schema')
        name = names[0].decode('utf-8', 'strict')
        parameter = (values[0] if values else b'').decode('utf-8', 'strict')
        if not name or name in parameters:
            raise RelayDenied('model_parameter_duplicate')
        parameters[name] = parameter
    return {
        'schema': 'requested-model-semantic-v1',
        'model_id': model,
        'max_mode': bool(maximum),
        'built_in_model': bool(builtin),
        'parameters': sorted(parameters.items()),
    }


def requested_model(body, content_type, content_encoding=''):
    identity = requested_identity(body, content_type, content_encoding)
    return identity['model_id'] if identity else None


LOCAL_METADATA = {
    '/aiserver.v1.AnalyticsService/SubmitLogs': 'application/json',
    '/aiserver.v1.AnalyticsService/TrackEvents': 'application/json',
    '/aiserver.v1.DashboardService/ListMarketplaces': 'application/proto',
    '/aiserver.v1.DashboardService/GetCliDownloadUrl': 'application/proto',
    '/aiserver.v1.DashboardService/GetTeamReposOrEmptyIfNotInTeam': 'application/proto',
    '/aiserver.v1.DashboardService/GetManagedSkills': 'application/proto',
    '/aiserver.v1.DashboardService/GetEffectiveUserPlugins': 'application/proto',
}
LOCAL_METADATA['/aiserver.v1.DashboardService/GetTeamHooks'] = 'application/proto'
LOCAL_METADATA['/aiserver.v1.DashboardService/GetTeamCommands'] = 'application/proto'
LOCAL_METADATA['/aiserver.v1.DashboardService/GetGlobalCommands'] = 'application/proto'
# The pinned client's OpenTelemetry exporter posts after tool operations. Drop
# these bounded telemetry bodies locally; they never reach the provider or grant
# any additional model/tool/network capability.
LOCAL_METADATA['/v1/traces'] = 'application/json'


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def parse_request(self):
        # Anything after an actual request line remains inside the strict RPC
        # failure contract, including resets while parsing headers.
        self._request_started = True
        return super().parse_request()

    def handle_one_request(self):
        self._request_started = False
        self.raw_requestline = None
        try:
            return super().handle_one_request()
        except ConnectionResetError:
            if self._request_started or self.raw_requestline is not None:
                raise
            self.close_connection = True
            record(
                dict(
                    event='client_connection_closed_before_request',
                    outcome='client_closed_before_request',
                    path=None,
                    status=None,
                    stage='request_line',
                    exception_kind='ConnectionResetError',
                    sent_bytes=0,
                    received_bytes=0,
                    request_category=None,
                    rejection_reason=None,
                    dispatch_denial=None,
                    provider_error=None,
                )
            )

    def do_GET(self):
        # Only readiness, never catalog contents, is exposed here. The cache is
        # private to this trial and populated by the unmodified client's request.
        if self.path != '/bench/catalog-ready':
            self.reject()
            return
        with self.server.state.lock:
            ready = self.server.state.catalog is not None and not self.server.state.failed
        self.send_response(200 if ready else 503)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def reject(self):
        self.send_response(403)
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True

    def read_body(self):
        if self.headers.get('Transfer-Encoding', '').lower() == 'chunked':
            data = bytearray()
            while True:
                line = self.rfile.readline(128)
                if not line.endswith(b'\r\n'):
                    raise ValueError()
                size = int(line.strip(), 16)
                if size < 0 or len(data) + size > BODY_LIMIT:
                    raise ValueError()
                if size == 0:
                    if self.rfile.read(2) != b'\r\n':
                        raise ValueError()
                    return bytes(data)
                block = self.rfile.read(size)
                if len(block) != size or self.rfile.read(2) != b'\r\n':
                    raise ValueError()
                data.extend(block)
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 <= size <= BODY_LIMIT:
            raise ValueError()
        data = self.rfile.read(size)
        if len(data) != size:
            raise ValueError()
        return data

    def do_POST(self):
        path = self.path
        state = self.server.state
        remote = None
        status, sent, received = None, 0, 0
        upstream_complete = False
        stream = False
        outcome = 'denied'
        stage = 'request'
        exception_kind = None
        provider_error = None
        dispatch_denial = None
        rejection = None
        category = None
        selected = None
        privacy_locked = False
        privacy_snapshot = None
        try:
            self.connection.settimeout(90)
            if path in LOCAL_METADATA:
                self.read_body()
                category = 'metadata'
                stage = 'request_admission'
                state.admit(path, b'', None, category, False)
                data = b'{}' if LOCAL_METADATA[path] == 'application/json' else b''
                self.send_response(200)
                self.send_header('Content-Type', LOCAL_METADATA[path])
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                status, outcome = 200, 'local_metadata'
                return
            if not allowed_path(path):
                with state.lock:
                    state.failed = True
                rejection = 'request_path_not_allowed'
                self.reject()
                return
            stage = 'request_body'
            data = self.read_body()
            headers = {
                k: v
                for k, v in self.headers.items()
                if k.lower()
                not in {
                    'host',
                    'authorization',
                    'connection',
                    'content-length',
                    'transfer-encoding',
                    'proxy-authorization',
                    'accept-encoding',
                    'connect-accept-encoding',
                }
            }
            # Tool exclusions must reach every agent inference request. A client
            # upgrade cannot silently drop the reviewed restriction.
            stream = path.rsplit('/', 1)[-1] in {
                'Run',
                'RunSSE',
                'StreamUnifiedChatWithTools',
                'StreamUnifiedChatWithToolsSSE',
            }
            if stream or path.endswith('/BidiAppend'):
                stage = 'request_tool_policy'
                admitted = {
                    n.strip() for n in self.headers.get('x-cursor-agent-allowed-tools', '').split(',') if n.strip()
                }
                if admitted != {'mcp_tool_call', 'get_mcp_tools_tool_call'}:
                    raise RelayDenied('tool_policy_mismatch')
            stage = 'request_identity'
            selected = (
                requested_identity(data, self.headers.get('Content-Type', ''), self.headers.get('Content-Encoding', ''))
                if path.endswith('/BidiAppend')
                else None
            )
            if os.environ.get('GAB_CURSOR_IDENTITY_PROBE') == '1' and (stream or selected is not None):
                if selected is not None:
                    record(
                        dict(
                            path=path,
                            outcome='identity_probe',
                            status=409,
                            sent_bytes=0,
                            received_bytes=0,
                            identity=selected,
                        )
                    )
                self.send_response(409)
                self.send_header('Content-Type', 'application/json')
                payload = b'{"code":"failed_precondition","message":"Benchmark identity probe completed."}'
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(payload)
                status, outcome = 409, 'probe_stopped'
                self.close_connection = True
                return
            stage = 'request_category'
            category = request_category(
                path, data, self.headers.get('Content-Type', ''), self.headers.get('Content-Encoding', '')
            )
            stage = 'request_admission'
            state.admit(path, data, selected, category, stream)
            catalog_key = (
                path,
                hashlib.sha256(data).hexdigest(),
                self.headers.get('Content-Type', ''),
                self.headers.get('Content-Encoding', ''),
            )
            if path == PRIVACY_PATH:
                # Hold through the audit write so concurrent identical requests
                # cannot race the first capture or precede its provenance row.
                state.privacy_lock.acquire()
                privacy_locked = True
                with state.lock:
                    if state.failed:
                        raise RelayDenied('session_already_failed')
                    cached = state.privacy_cache
                age = time.monotonic() - cached['captured_at'] if cached is not None else None
                if cached is not None and cached['key'] == catalog_key and 0 <= age < PRIVACY_CACHE_SECONDS:
                    privacy_snapshot = dict(cached['proof'], event='served', age_ms=int(age * 1000))
                    # This exact response was completely fetched and validated
                    # before caching. A cancelled downstream metadata reader has
                    # the same known-complete provenance as an uncached reply.
                    status, upstream_complete, stage = 200, True, 'client_write'
                    self.send_response(200)
                    for name, value in cached['headers'].items():
                        self.send_header(name, value)
                    self.send_header('Content-Length', str(len(cached['body'])))
                    self.end_headers()
                    stage = 'client_write'
                    self.wfile.write(cached['body'])
                    outcome = 'trial_privacy_cache'
                    return
            if path == '/aiserver.v1.AiService/AvailableModels':
                with state.lock:
                    cached = state.catalog
                if cached is not None:
                    if cached[0] != catalog_key:
                        raise RelayDenied('catalog_request_changed')
                    response_headers, payload = cached[1:]
                    self.send_response(200)
                    for name, value in response_headers.items():
                        self.send_header(name, value)
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    status, outcome = 200, 'trial_catalog_cache'
                    return
            stage = 'upstream_connect'
            headers['Authorization'] = 'Bearer ' + os.environ['GAB_CURSOR_ACCESS_TOKEN']
            headers['Host'] = 'api2.cursor.sh'
            headers['Content-Length'] = str(len(data))
            headers['Connection'] = 'close'
            headers['Accept-Encoding'] = 'identity'
            headers['Connect-Accept-Encoding'] = 'identity'
            remote = http.client.HTTPSConnection('api2.cursor.sh', timeout=90)
            remote.request('POST', path, body=data, headers=headers)
            sent = len(data)
            stage = 'upstream_headers'
            response = remote.getresponse()
            status = response.status
            secret = os.environ['GAB_CURSOR_ACCESS_TOKEN'].encode()
            stage = 'response_credentials'
            if response.getheader('Content-Encoding') not in {None, 'identity'} or response.getheader(
                'Connect-Content-Encoding'
            ) not in {None, 'identity'}:
                raise ValueError('Unqualified response compression')
            self.send_response(status)
            for name in ('Content-Type', 'Content-Encoding', 'Connect-Content-Encoding', 'Grpc-Status'):
                if response.getheader(name):
                    if secret in response.getheader(name).encode():
                        raise ValueError('Credential echo denied')
                    self.send_header(name, response.getheader(name))
            self.send_header('Transfer-Encoding', 'chunked')
            self.send_header('Connection', 'close')
            self.end_headers()
            pending = b''
            metadata = bytearray()
            while True:
                stage = 'upstream_read'
                block = response.read1(65536)
                if not block:
                    break
                received += len(block)
                upstream_complete = response.length == 0
                if received > 64_000_000:
                    raise ValueError()
                if not stream:
                    # Account responses are bounded and buffered in full so an
                    # echoed credential cannot escape across read boundaries.
                    metadata.extend(block)
                    continue
                if stream:
                    stage = 'stream_encoding'
                    content_type = (response.getheader('Content-Type') or '').lower()
                    # The pinned connect-es patch treats text/event-stream as
                    # binary Connect envelopes, not textual SSE data records.
                    binary = content_type in {'application/connect+proto', 'text/event-stream'}
                    if not binary and content_type not in {
                        'application/connect+json',
                        'application/connect+json; charset=utf-8',
                    }:
                        raise ValueError('Unqualified stream encoding')
                    pending += block
                    admitted_blocks = []
                    while len(pending) >= 5:
                        stage = 'frame_header'
                        size = int.from_bytes(pending[1:5], 'big')
                        if size > 8_000_000 or pending[0] not in {0, 2}:
                            raise ValueError()
                        if len(pending) < size + 5:
                            break
                        wire, pending = pending[: size + 5], pending[size + 5 :]
                        stage = 'response_credentials'
                        if secret in wire:
                            raise ValueError('Credential echo denied')
                        if wire[0] == 0:
                            stage = 'frame_dispatch'
                            validate_server_frame(wire[5:], binary=binary)
                        else:
                            stage = 'frame_end'
                            error = json.loads(wire[5:]).get('error')
                            if error:
                                provider_error = provider_error_summary(error)
                                raise ValueError('Provider stream failed')
                        admitted_blocks.append(wire)
                    block = b''.join(admitted_blocks)
                    if not block:
                        continue
                stage = 'client_write'
                self.wfile.write(f'{len(block):x}\r\n'.encode() + block + b'\r\n')
                self.wfile.flush()
            if pending:
                raise ValueError('Incomplete stream')
            upstream_complete = True
            if not stream:
                stage = 'response_credentials'
                if secret in metadata:
                    raise ValueError('Credential echo denied')
                if path == '/aiserver.v1.AiService/AvailableModels' and status == 200:
                    response_headers = {
                        name: response.getheader(name)
                        for name in ('Content-Type', 'Content-Encoding', 'Connect-Content-Encoding', 'Grpc-Status')
                        if response.getheader(name)
                    }
                    with state.lock:
                        if state.catalog is not None:
                            raise RelayDenied('repeated_catalog_population')
                        state.catalog = (catalog_key, response_headers, bytes(metadata))
                if path == PRIVACY_PATH and status == 200:
                    response_headers = {
                        name: response.getheader(name)
                        for name in ('Content-Type', 'Content-Encoding', 'Connect-Content-Encoding', 'Grpc-Status')
                        if response.getheader(name)
                    }
                    validate_privacy_response(response_headers, metadata)
                    proof = dict(
                        request_sha256=hashlib.sha256(
                            json.dumps(catalog_key, separators=(',', ':')).encode()
                        ).hexdigest(),
                        response_sha256=hashlib.sha256(
                            json.dumps(response_headers, sort_keys=True, separators=(',', ':')).encode()
                            + b'\0'
                            + metadata
                        ).hexdigest(),
                    )
                    with state.lock:
                        if state.failed:
                            raise RelayDenied('session_already_failed')
                        state.privacy_generation += 1
                        proof['generation'] = state.privacy_generation
                        state.privacy_cache = dict(
                            key=catalog_key,
                            headers=response_headers,
                            body=bytes(metadata),
                            proof=proof,
                            captured_at=time.monotonic(),
                        )
                    privacy_snapshot = dict(proof, event='captured', age_ms=0)
                stage = 'client_write'
                if metadata:
                    self.wfile.write(f'{len(metadata):x}\r\n'.encode() + metadata + b'\r\n')
            self.wfile.write(b'0\r\n\r\n')
            outcome = 'completed' if status == 200 else 'provider_error'
            if status != 200:
                with state.lock:
                    state.failed = True
        except (BrokenPipeError, ConnectionResetError) as exc:
            exception_kind = type(exc).__name__
            if not stream and status == 200 and upstream_complete:
                outcome = 'client_closed_after_metadata'
            else:
                with state.lock:
                    state.failed = True
                outcome = 'failed'
            self.close_connection = True
        except Exception as exc:
            exception_kind = type(exc).__name__
            if isinstance(exc, DispatchDenied):
                dispatch_denial = exc.summary
            if isinstance(exc, RelayDenied):
                rejection = exc.reason
            elif stage.startswith('request_'):
                rejection = stage + '_invalid'
            with state.lock:
                state.failed = True
            outcome = 'failed'
            self.close_connection = True
        finally:
            if remote:
                remote.close()
            try:
                record(
                    dict(
                        path=path if RPC.fullmatch(path) else None,
                        outcome=outcome,
                        status=status,
                        sent_bytes=sent,
                        received_bytes=received,
                        stage=stage,
                        exception_kind=exception_kind,
                        provider_error=provider_error,
                        dispatch_denial=dispatch_denial,
                        rejection_reason=rejection,
                        request_category=category,
                        request_counts=dict(state.counts),
                        model_identity=selected if rejection == 'model_identity_mismatch' else None,
                        **({'privacy_snapshot': privacy_snapshot} if privacy_snapshot else {}),
                    )
                )
            finally:
                if privacy_locked:
                    state.privacy_lock.release()


class GatewayHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # No default traceback with free-form exception data in the JSON audit.
        # Unexpected errors are still fatal, with complete safe frame locations.
        kind, _, tb = sys.exc_info()
        frames = []
        while tb is not None:
            frames.append(
                dict(
                    module=tb.tb_frame.f_globals.get('__name__', '<runtime>'),
                    function=tb.tb_frame.f_code.co_name,
                    line=tb.tb_lineno,
                )
            )
            tb = tb.tb_next
        with self.state.lock:
            self.state.failed = True
        record(
            dict(
                event='http_connection_error',
                outcome='failed',
                path=None,
                status=None,
                stage='http_connection',
                exception_kind=kind.__name__ if kind else 'unknown',
                rejection_reason='unclassified_http_connection_error',
                dispatch_denial=None,
                provider_error=None,
                sent_bytes=0,
                received_bytes=0,
                frames=frames,
            )
        )


if __name__ == '__main__':
    server = GatewayHTTPServer(('0.0.0.0', 8080), Handler)
    server.daemon_threads = True
    server.state = State()
    server.serve_forever()
