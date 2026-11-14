"""Versioned diagnostics, independent of rewards. Never serialize exception text.

Only trusted boundaries assign causes. Unknown exceptions remain unknown;
submitted programs cannot turn their exception strings into grading evidence.
"""

import subprocess
import urllib.error
import json

VERSION = 'failure-v1'
MESSAGES = {
    'app_scope_lost': 'The app is outside the permitted interaction scope.',
    'policy_violation': 'This capability is not permitted.',
    'invalid_arguments': 'Arguments do not match the public contract.',
    'target_unavailable': 'The requested target is unavailable or not uniquely actionable.',
    'target_ambiguous': 'Multiple elements match this exact target. Inspect the current UI and choose a unique target or use screenshot coordinates.',
    'device_unavailable': 'The dedicated research emulator is absent, offline, or unauthorized. This is an infrastructure failure; restore its connection and verify its runtime before a new run.',
    'simulator_ambiguity': 'The simulator returned ambiguous destinations for this permitted action.',
    'action_timeout': 'The operation timed out; the underlying reason is unknown.',
    'app_not_ready': 'The application did not become ready.',
    'reset_failure': 'The requested reset did not complete.',
    'infrastructure_error': 'A runtime or transport operation failed.',
    'unknown_operation_error': 'The operation failed for an unclassified reason.',
    'provider_timeout': 'The inference provider timed out.',
    'provider_rate_limit': 'The inference provider reported a rate limit.',
    'provider_error': 'The inference provider reported an error.',
    'provider_capacity': 'The selected model is at capacity; the provider rejected the turn. This is a provider availability failure, not a model answer failure. No automatic retry was performed.',
    'native_operation_in_flight': 'The native relay still has an unfinished device operation. No new operation was dispatched. Review the preceding operation and its correlated driver evidence; this is not a model answer failure.',
    'provider_transport_error': 'The inference provider connection failed.',
    'capability_unavailable': 'The required tool configuration was unavailable.',
    'budget_exhausted': 'The request or model budget was exhausted.',
    'evidence_overflow': 'The evidence limit was exceeded; partial evidence is not admitted.',
    'context_overflow': 'The context or output limit was exceeded.',
    'execution_timeout': 'The execution time limit was exceeded.',
    'resource_limit': 'The execution resource limit was exceeded.',
    'process_error': 'The process exited unsuccessfully.',
    'incomplete_trajectory': 'The agent did not record a normal completion.',
    'missing_submission': 'No submission was produced.',
    'malformed_submission': 'The submission does not meet the artifact contract.',
    'failed_precondition': 'An authored positive precondition did not match; this does not establish an environment failure.',
    'behavioral_mismatch': 'A behavioral assertion did not match.',
    'missing_checks': 'Required preconditions, assertions or journey actions are absent.',
    'incomparable_pair': 'The executions do not have comparable action/assertion definitions.',
    'unstable_execution': 'Repeated executions of the same artifact on one version disagree.',
    'legacy_ambiguous_denial': 'A historical denial does not distinguish policy from operation failure.',
}
# Causes explained by the evaluated model's own requests or submitted artifact.
MODEL_CAUSES = frozenset(
    {
        'policy_violation',
        'invalid_arguments',
        'budget_exhausted',
        'context_overflow',
        'execution_timeout',
        'resource_limit',
        'process_error',
        'missing_submission',
        'malformed_submission',
        'failed_precondition',
        'behavioral_mismatch',
        'missing_checks',
        'incomparable_pair',
        'unstable_execution',
    }
)
# These describe the generated program only when it is the process being executed.
EXECUTION_ONLY_CAUSES = frozenset({'execution_timeout', 'resource_limit', 'process_error'})


class Failure(ValueError):
    def __init__(self, cause):
        if cause not in MESSAGES:
            raise ValueError('unknown diagnostic cause')
        self.cause = cause
        super().__init__(MESSAGES[cause])


def checked(function, *args, **kwargs):
    """Only wrap argument validation, never an adapter/operation invocation."""
    try:
        return function(*args, **kwargs)
    except Failure:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        raise Failure('invalid_arguments') from exc


def cause_of(exc):
    if isinstance(exc, Failure):
        return exc.cause
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)) or (
        type(exc).__module__.startswith('playwright.') and type(exc).__name__ == 'TimeoutError'
    ):
        return 'action_timeout'
    if isinstance(exc, (OSError, urllib.error.URLError)):
        return 'infrastructure_error'
    return 'unknown_operation_error'


def issue(exc, *, phase, operation, impact, source=None):
    from gui_agent_bench.failure_detail import detail, operational

    cause = cause_of(exc)
    # No exception messages, URLs, paths, request bodies, or arbitrary class names.
    result = dict(
        version=VERSION,
        phase=phase,
        operation=operation,
        result='failed',
        cause=cause,
        impact=impact,
        message=MESSAGES[cause],
    )
    # A small safe diagnostic vocabulary; exception messages remain excluded.
    kinds = {
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
        'Failure',
    }
    result['exception_type'] = type(exc).__name__ if type(exc).__name__ in kinds else 'Exception'
    if operational(exc):
        result['detail'] = detail(exc)
    if source is not None:
        result['source'] = source
    related, seen = [], {id(exc)}
    child = exc.__cause__
    while child is not None and id(child) not in seen:
        seen.add(id(child))
        related.append(cause_of(child))
        child = child.__cause__
    if related:
        result['underlying_causes'] = related
    return result


def model_attributable(item):
    """Whether one recorded diagnostic is explained by the evaluated model.

    Setup/controller failures, provider/infrastructure causes and unclassified
    or ambiguous causes are never attributed to the model.
    """
    cause, phase = item.get('cause'), item.get('phase')
    if phase in {'setup', 'controller'} or cause not in MODEL_CAUSES:
        return False
    return cause not in EXECUTION_ONLY_CAUSES or phase == 'execution'


def model_zero(issues, *, control=False):
    """True when every zero-credit diagnostic is a model outcome, not an error to review.

    Scripted controls and reference solutions must always produce valid artifacts,
    so their invalid results are never model outcomes.
    """
    zero = [i for i in issues if i.get('impact') == 'zero_credit']
    return not control and bool(zero) and all(model_attributable(i) for i in zero)


def explain(issues):
    """One readable line per distinct recorded cause, in recorded order."""
    from gui_agent_bench.failure_detail import describe

    seen, lines = set(), []
    for item in issues:
        cause = item.get('cause')
        if cause not in MESSAGES:
            continue
        try:
            context = describe(item.get('detail'))
        except (ValueError, TypeError):
            context = 'Diagnostic detail is malformed; review the retained evidence.'
        key = (cause, context)
        if key not in seen:
            seen.add(key)
            lines.append(f'{cause}: {MESSAGES[cause]}' + (f' Observed: {context}.' if context else ''))
    return '; '.join(lines)


def public_error(exc):
    cause = cause_of(exc)
    return {'cause': cause, 'message': MESSAGES[cause]}


def result_cause(result):
    """Recognize only a complete, curated broker diagnostic, never arbitrary text."""
    try:
        content = result['content']
        if result.get('isError') is not True or len(content) != 1 or content[0]['type'] != 'text':
            return None
        value = json.loads(content[0]['text'])
        cause = value['cause']
        if value == public_error(Failure(cause)):
            return cause
    except (KeyError, ValueError, TypeError):
        pass
    return None


def authoring_feedback(result, tool):
    """A failed permitted target/argument request needs no reset or action retry.

    Execution errors still prevent credit. Unknown, transport, security and
    evidence failures are deliberately excluded from this authoring allowance.
    """
    if tool != 'gui_step':
        return None
    cause = result_cause(result)
    return cause if cause in {'invalid_arguments', 'target_ambiguous', 'target_unavailable'} else None


def diagnostics(issues):
    """Primary means first blocking diagnostic in recorded order, not root cause.

    Cross-process lists are grouped by source, not claimed to be a global timeline.
    """
    primary = next(
        (i for i, item in enumerate(issues) if item['impact'] == 'zero_credit'),
        next((i for i, item in enumerate(issues) if item['impact'] == 'pair_dependent'), 0 if issues else None),
    )
    return {'version': VERSION, 'primary_issue': primary, 'issues': issues, 'ordering': 'source_order_not_global_time'}


def record_issues(records, *, phase, source):
    issues = []
    for index, record in enumerate(records):
        location = {'file': source, 'record_index': index}
        if isinstance(record.get('failure'), dict) and record['failure'].get('version') == VERSION:
            issues.append({**record['failure'], 'source': location})
        elif record.get('denied'):
            issues.append(
                issue(
                    Failure('legacy_ambiguous_denial'),
                    phase=phase,
                    operation='unknown',
                    impact='zero_credit' if phase == 'execution' else 'feedback',
                    source=location,
                )
            )
        if 'assertion' in record and record.get('matched') is False:
            precondition = record['assertion'].get('precondition') is True
            issues.append(
                issue(
                    Failure('failed_precondition' if precondition else 'behavioral_mismatch'),
                    phase=phase,
                    operation='assert',
                    impact='zero_credit' if precondition else 'pair_dependent',
                    source=location,
                )
            )
    return issues


def provider_cause(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return 'provider_rate_limit' if exc.code == 429 else 'provider_error'
    if isinstance(exc, TimeoutError) or (
        isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, TimeoutError)
    ):
        return 'provider_timeout'
    return 'provider_transport_error' if isinstance(exc, (OSError, urllib.error.URLError)) else 'provider_error'


def summarize(results, planned):
    """Counts are per planned trial/pair, not conditional success rates."""
    counts = {}
    for result in results:
        issues = result.get('diagnostics', {}).get('issues', [])
        for cause in {item['cause'] for item in issues}:
            counts[cause] = counts.get(cause, 0) + 1
    return {
        'version': VERSION,
        'planned_units': planned,
        'recorded_units': len(results),
        'units_by_cause': counts,
        'counts_overlap': True,
        'graded_units': sum(r.get('status') == 'graded' for r in results),
        'units_with_blocking_diagnostics': sum(
            any(i['impact'] == 'zero_credit' for i in r.get('diagnostics', {}).get('issues', [])) for r in results
        ),
        'cause_rates_per_planned_unit': {k: v / planned if planned else None for k, v in counts.items()},
        'diagnostic_coverage': sum('diagnostics' in r for r in results),
        'automatic_retries': False,
    }
