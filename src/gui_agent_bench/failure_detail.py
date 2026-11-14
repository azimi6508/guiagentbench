"""Operator-only failure evidence. Never serialize exception text or locals.

Facts describe an observation, not a root-cause verdict. Public tool replies
deliberately omit this extension. Native RPC carries it only between trusted
processes, using the same failure ID as the driver's own record.
"""

from pathlib import Path
import re
import uuid

VERSION = 'failure-detail-v1'
PACKAGE = Path(__file__).resolve().parent
COMPONENTS = {'web_adapter', 'native_driver', 'native_extended_driver', 'native_relay', 'native_adapter'}
STAGES = {
    'target_action',
    'ui_assertion',
    'device_operation',
    'device_check',
    'relay_wait',
    'transport',
    'evidence_validation',
}
FACTS = {
    'pre_action_matches': lambda v: type(v) is int and 0 <= v < 2**31,
    'action_dispatched': lambda v: type(v) is bool,
    'center_in_viewport': lambda v: type(v) is bool,
    'center_hits_target': lambda v: type(v) is bool,
    'pointer_events_none': lambda v: type(v) is bool,
    'activation_target': lambda v: v in ('native_control', 'associated_label'),
    'associated_labels': lambda v: type(v) is int and 0 <= v < 2**31,
    'visible_labels': lambda v: type(v) is int and 0 <= v < 2**31,
    'evidence_bytes': lambda v: type(v) is int and 0 <= v < 2**31,
    'evidence_limit_bytes': lambda v: type(v) is int and 0 <= v < 2**31,
    'target_matches': lambda v: type(v) is int and 0 <= v < 2**31,
    'visible': lambda v: type(v) is bool,
    'enabled': lambda v: type(v) is bool,
    'page_closed': lambda v: type(v) is bool,
    'browser_connected': lambda v: type(v) is bool,
    'device_state': lambda v: v in ('device', 'absent', 'offline', 'unauthorized', 'unknown'),
    'observation': lambda v: v in ('before_action', 'after_failure', 'transport'),
    'probe_failed': lambda v: type(v) is bool,
    'diagnostic_valid': lambda v: type(v) is bool,
    'http_status': lambda v: type(v) is int and 100 <= v <= 599,
    'process_returncode': lambda v: type(v) is int and -65536 <= v <= 65536,
    'os_errno': lambda v: type(v) is int and 0 <= v <= 4096,
}
KINDS = {
    'ValueError',
    'TypeError',
    'KeyError',
    'RuntimeError',
    'TimeoutError',
    'OSError',
    'FileNotFoundError',
    'ConnectionError',
    'HTTPError',
    'URLError',
    'CalledProcessError',
    'TimeoutExpired',
    'Failure',
    'AssertionError',
    'UiObjectNotFoundError',
    'UiAutomationNotConnectedError',
    'ReadTimeout',
    'TargetClosedError',
    'Error',
    'other',
}


def operational(exc):
    """Verifier deductions must replay byte-for-byte, without invented events."""
    current, seen = exc, set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if current.__traceback__ is not None or getattr(current, '_bench_failure_detail', None) is not None:
            return True
        current = current.__cause__
    return False


def validate(value):
    """Reject extra fields, arbitrary strings and paths from native transport."""
    if not isinstance(value, dict) or set(value) - {
        'version',
        'failure_id',
        'component',
        'stage',
        'facts',
        'elapsed_ms',
        'correlation_id',
        'exception_kind',
        'frames',
    }:
        raise ValueError('Invalid failure detail')
    if (
        value.get('version') != VERSION
        or not isinstance(value.get('failure_id'), str)
        or not re.fullmatch('[0-9a-f]{32}', value['failure_id'])
    ):
        raise ValueError('Invalid failure detail identity')
    for key, values in (('component', COMPONENTS), ('stage', STAGES), ('exception_kind', KINDS)):
        if key in value and (not isinstance(value[key], str) or value[key] not in values):
            raise ValueError('Invalid failure detail vocabulary')
    if 'elapsed_ms' in value and (type(value['elapsed_ms']) is not int or not 0 <= value['elapsed_ms'] <= 86_400_000):
        raise ValueError('Invalid failure duration')
    if 'correlation_id' in value and (
        not isinstance(value['correlation_id'], str) or not re.fullmatch('[0-9a-f]{32}', value['correlation_id'])
    ):
        raise ValueError('Invalid failure correlation')
    facts = value.get('facts', {})
    if not isinstance(facts, dict) or any(k not in FACTS or not FACTS[k](v) for k, v in facts.items()):
        raise ValueError('Invalid failure observations')
    frames = value.get('frames', [])
    if not isinstance(frames, list):
        raise ValueError('Invalid failure locations')
    for frame in frames:
        if (
            not isinstance(frame, dict)
            or set(frame) != {'file', 'line'}
            or not isinstance(frame['file'], str)
            or not re.fullmatch(r'(?:[a-z_][a-z0-9_]*/)*[a-z_][a-z0-9_]*\.py', frame['file'])
            or not (PACKAGE / frame['file']).is_file()
            or type(frame['line']) is not int
            or not 1 <= frame['line'] <= 1_000_000
        ):
            raise ValueError('Invalid failure location')
    return {**value, 'facts': dict(facts), 'frames': [dict(f) for f in frames]}


def detail(exc):
    """Keep the first observed identity through wrappers and repeated logging."""
    current, seen, chain = exc, set(), []
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        saved = getattr(current, '_bench_failure_detail', None)
        if saved is not None:
            value = validate(saved)
            if not value['frames'] and not getattr(current, '_bench_detail_remote', False):
                value['frames'] = locations(current)
                current._bench_failure_detail = validate(value)
            return value
        current = current.__cause__
    origin = chain[-1]
    kind = type(origin).__name__
    value = {
        'version': VERSION,
        'failure_id': uuid.uuid4().hex,
        'exception_kind': kind if kind in KINDS else 'other',
        'frames': [frame for cause in chain for frame in locations(cause)],
        'facts': {},
    }
    # Never include command, stdout/stderr, URL, filename, args or source text.
    for field, attribute in (('process_returncode', 'returncode'), ('os_errno', 'errno')):
        number = getattr(origin, attribute, None)
        if FACTS[field](number):
            value['facts'][field] = number
    exc._bench_failure_detail = validate(value)
    return validate(value)


def locations(exc):
    frames = []
    tb = exc.__traceback__
    while tb is not None:
        try:
            relative = Path(tb.tb_frame.f_code.co_filename).resolve().relative_to(PACKAGE).as_posix()
        except ValueError:
            pass
        else:
            frames.append({'file': relative, 'line': tb.tb_lineno})
        tb = tb.tb_next
    return frames


def attach(exc, *, component, stage, facts=None, elapsed_ms=None, correlation_id=None):
    value = detail(exc)
    value.update(component=component, stage=stage)
    value['facts'].update(facts or {})
    if elapsed_ms is not None:
        value['elapsed_ms'] = elapsed_ms
    if correlation_id is not None:
        value['correlation_id'] = correlation_id
    exc._bench_failure_detail = validate(value)
    return exc


def restore(exc, value):
    exc._bench_failure_detail = validate(value)
    exc._bench_detail_remote = True
    return exc


def native_result(exc, *, component, correlation_id, elapsed_ms):
    """One record for both the private driver log and its trusted RPC reply."""
    from gui_agent_bench.failures import issue

    attach(exc, component=component, stage='device_operation', correlation_id=correlation_id, elapsed_ms=elapsed_ms)
    failure = issue(exc, phase='native_driver', operation='device_operation', impact='operation_failed')
    return {'error': True, 'cause': failure['cause'], 'detail': failure['detail']}, failure


def describe(value):
    """A compact, safe operator explanation; historical records stay generic."""
    if value is None:
        return ''
    value = validate(value)
    facts, parts = value['facts'], []
    if 'component' in value:
        parts.append(value['component'] + '/' + value.get('stage', 'transport'))
    if 'target_matches' in facts:
        parts.append(f"exact matches observed: {facts['target_matches']}")
    if 'evidence_bytes' in facts and 'evidence_limit_bytes' in facts:
        parts.append(
            f"complete UI evidence: {facts['evidence_bytes']} bytes; limit: {facts['evidence_limit_bytes']} bytes; nothing truncated"
        )
    if 'pre_action_matches' in facts:
        parts.append(f"exact matches before action: {facts['pre_action_matches']}")
    for key in (
        'visible',
        'enabled',
        'page_closed',
        'browser_connected',
        'action_dispatched',
        'center_in_viewport',
        'center_hits_target',
        'pointer_events_none',
    ):
        if key in facts:
            parts.append(f'{key}={str(facts[key]).lower()}')
    if 'device_state' in facts:
        parts.append('dedicated device: ' + facts['device_state'])
    if 'activation_target' in facts:
        parts.append('click activation target: ' + facts['activation_target'])
    if 'associated_labels' in facts:
        parts.append(f"associated labels: {facts['associated_labels']}; visible: {facts.get('visible_labels', 0)}")
    if facts.get('probe_failed'):
        parts.append('some diagnostic checks unavailable')
    if facts.get('diagnostic_valid') is False:
        parts.append('native diagnostic rejected as malformed')
    for key in ('http_status', 'process_returncode', 'os_errno'):
        if key in facts:
            parts.append(f'{key}={facts[key]}')
    if 'elapsed_ms' in value:
        parts.append(f"elapsed {value['elapsed_ms']} ms")
    if value.get('frames'):
        frame = value['frames'][-1]
        parts.append(f"framework location: {frame['file']}:{frame['line']}")
    parts.append('failure ID ' + value['failure_id'])
    return '; '.join(parts)
