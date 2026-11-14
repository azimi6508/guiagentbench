"""Positive-list inference diagnostics. Never retain free-form provider text.

Bodies are inspected in memory only. Unknown codes become ``unknown`` rather
than being copied or guessed from messages. This is not a redaction algorithm.
"""

import json
import math
import http.client
import socket
import ssl
import urllib.error

VERSION = 'inference-v1'
ERROR_BODY_LIMIT = 65_536
RESPONSE_LIMIT = 8_000_000
ERROR_TYPES = frozenset(
    {
        'context_length_exceeded',
        'max_tokens_exceeded',
        'token_limit_exceeded',
        'string_too_long',
        'authentication',
        'permission_denied',
        'payment_required',
        'rate_limit_exceeded',
        'provider_overloaded',
        'provider_unavailable',
        'invalid_request',
        'invalid_prompt',
        'not_found',
        'precondition_failed',
        'payload_too_large',
        'unprocessable',
        'content_policy_violation',
        'refusal',
        'invalid_image',
        'image_too_large',
        'image_too_small',
        'unsupported_image_format',
        'image_not_found',
        'image_download_failed',
        'server',
        'timeout',
        'unmapped',
    }
)
ERROR_CODES = ERROR_TYPES | {'server_error', 'invalid_api_key', 'insufficient_credits'}
FINISH_REASONS = frozenset({'stop', 'length', 'tool_calls', 'function_call', 'content_filter', 'error'})
# Upstream (e.g. Gemini) finish reasons forwarded by OpenRouter as native_finish_reason.
NATIVE_FINISH_REASONS = frozenset(
    {
        'STOP',
        'MAX_TOKENS',
        'SAFETY',
        'RECITATION',
        'LANGUAGE',
        'OTHER',
        'BLOCKLIST',
        'PROHIBITED_CONTENT',
        'SPII',
        'MALFORMED_FUNCTION_CALL',
        'IMAGE_SAFETY',
        'UNEXPECTED_TOOL_CALL',
        'TOO_MANY_TOOL_CALLS',
        'MISSING_THOUGHT_SIGNATURE',
        'FINISH_REASON_UNSPECIFIED',
    }
)


def native_reason(choice):
    value = choice.get('native_finish_reason') if isinstance(choice, dict) else None
    if value is None:
        return None
    if isinstance(value, str) and value.upper() in NATIVE_FINISH_REASONS:
        return value.upper()
    return 'unknown'


def status_code(value):
    return value if type(value) is int and 100 <= value <= 599 else None


def request_summary(payload, size):
    choice = payload.get('tool_choice')
    if isinstance(choice, dict):
        choice = 'function' if choice.get('type') == 'function' else 'unknown'
    elif choice not in ('auto', 'none', 'required', None):
        choice = 'unknown'
    return {
        'request_bytes': size,
        'message_count': len(payload['messages']),
        'tool_count': len(payload.get('tools') or []),
        'tool_choice': choice,
        'stream_requested': payload.get('stream') is True,
        'max_tokens': 4096,
    }


def error_summary(error):
    error = error if isinstance(error, dict) else {}
    code = error.get('code')
    code = status_code(code) or (code if isinstance(code, str) and code in ERROR_CODES else 'unknown')
    metadata = error.get('metadata')
    kind = metadata.get('error_type') if isinstance(metadata, dict) else None
    return {'error_code': code, 'error_type': kind if isinstance(kind, str) and kind in ERROR_TYPES else 'unknown'}


def http_error_summary(error):
    """A bounded diagnostic sample of an already failed response, never evidence."""
    try:
        data = error.read(ERROR_BODY_LIMIT + 1)
        if len(data) > ERROR_BODY_LIMIT:
            return {'error_body': 'oversized'}
        if not data:
            return {'error_body': 'empty'}
        value = json.loads(data)
        if isinstance(value, dict) and 'error' in value:
            return {'error_body': 'structured', **error_summary(value['error'])}
        return {'error_body': 'unrecognized'}
    except (ValueError, OSError, TypeError, AttributeError, RecursionError, http.client.HTTPException):
        return {'error_body': 'unavailable_or_invalid'}
    finally:
        try:
            error.close()
        except OSError:
            pass


def inspect_response(value):
    """Return a safe error and finish reasons; never retain arbitrary response fields."""
    if not isinstance(value, dict):
        raise ValueError('invalid response envelope')
    choices = value.get('choices', [])
    native = next((n for n in map(native_reason, choices if isinstance(choices, list) else []) if n), None)

    def failed(error, reasons):
        summary = {**error_summary(error), 'error_envelope': error is not None}
        if native is not None:
            summary['native_finish_reason'] = native
        return summary, reasons

    if 'error' in value:
        return failed(value['error'], [])
    if not isinstance(choices, list) or not ('choices' in value or isinstance(value.get('usage'), dict)):
        raise ValueError('invalid response choices')
    reasons = set()
    for choice in choices:
        if not isinstance(choice, dict):
            raise ValueError('invalid response choice')
        if 'error' in choice:
            return failed(choice['error'], [])
        reason = choice.get('finish_reason')
        if reason is not None:
            reasons.add(reason if isinstance(reason, str) and reason in FINISH_REASONS else 'unknown')
        if reason == 'error':
            return failed(None, ['error'])
    return None, sorted(reasons)


def usage_summary(value):
    usage = value.get('usage')
    if not isinstance(usage, dict) or not usage:
        return None
    # Strings, booleans, nested values, non-finite and implausibly large numbers
    # cannot turn the accounting log into a provider-controlled text channel.
    result = {}
    for key in ('prompt_tokens', 'completion_tokens', 'total_tokens', 'cost'):
        number = usage.get(key)
        result[key] = number if type(number) in (int, float) and 0 <= number <= 1e12 and math.isfinite(number) else None
    return result


def credential_echo(value, secret):
    """Reject an exact credential echo even inside JSON-escaped success fields."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str) and secret in item:
            return True
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return False


def transport_reason(error):
    """Use exception types only, never message matching or DNS/URL text."""
    error = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(error, TimeoutError):
        return 'timeout'
    if isinstance(error, socket.gaierror):
        return 'dns_failure'
    if isinstance(error, ssl.SSLError):
        return 'tls_failure'
    if isinstance(error, ConnectionResetError):
        return 'connection_reset'
    if isinstance(error, ConnectionRefusedError):
        return 'connection_refused'
    return 'connection_failed'
