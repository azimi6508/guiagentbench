"""Typed Codex failures and cumulative usage; no assistant-prose heuristics."""

from gui_agent_bench.failures import Failure


def error_cause(value, *, startup=False):
    if isinstance(value, dict):
        tag = next(iter(value), '') if len(value) == 1 else ''
    else:
        tag = value
    return {
        'usageLimitExceeded': 'provider_rate_limit',
        'rateLimitExceeded': 'provider_rate_limit',
        'contextWindowExceeded': 'context_overflow',
        'sessionBudgetExceeded': 'budget_exhausted',
        'unauthorized': 'capability_unavailable' if startup else 'provider_error',
        'httpConnectionFailed': 'provider_transport_error',
        'responseStreamConnectionFailed': 'provider_transport_error',
        'responseStreamDisconnected': 'provider_transport_error',
        'responseTooManyFailedAttempts': 'provider_transport_error',
        'serverOverloaded': 'provider_capacity',
    }.get(tag if isinstance(tag, str) else '', 'provider_error')


class Usage:
    def __init__(self):
        self.total = None
        self.last = None
        self.context_window = None

    def update(self, value):
        keys = (
            'inputTokens',
            'cachedInputTokens',
            'cacheWriteInputTokens',
            'outputTokens',
            'reasoningOutputTokens',
            'totalTokens',
        )
        result = {}
        for key in keys:
            number = value.get('total', {}).get(key)
            if number is not None and (type(number) is not int or number < 0):
                raise Failure('incomplete_trajectory')
            if number is not None and self.total and self.total.get(key) is not None and number < self.total[key]:
                raise Failure('incomplete_trajectory')
            result[key] = number
        self.total, self.last = result, value.get('last')
        self.context_window = value.get('modelContextWindow')

    def record(self):
        return dict(
            usage=self.total,
            usage_last=self.last,
            model_context_window=self.context_window,
            usage_source='codex.thread/tokenUsage/updated',
            usage_complete=self.total is not None,
            provider_cost_usd=None,
            billing_mode='chatgpt_subscription',
            model_requests=None,
            model_steps=None,
            per_request_output_token_cap=None,
        )
