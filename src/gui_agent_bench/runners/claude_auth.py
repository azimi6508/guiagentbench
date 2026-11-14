"""Select exactly one Anthropic credential from the environment; never persist it.

ANTHROPIC_API_KEY bills the API account. CLAUDE_CODE_OAUTH_TOKEN (from
`claude setup-token`) uses a Claude subscription. Setting both is ambiguous
and rejected, so the billing mode is always explicit.
"""

import os

KINDS = {'api_key': 'ANTHROPIC_API_KEY', 'oauth': 'CLAUDE_CODE_OAUTH_TOKEN'}


def credentials():
    present = {kind: os.environ[name] for kind, name in KINDS.items() if os.environ.get(name)}
    if len(present) != 1:
        raise ValueError('Set exactly one of ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN for Claude Code')
    kind, value = next(iter(present.items()))
    if any(ord(c) < 33 or ord(c) > 126 for c in value) or len(value) > 4096:
        raise ValueError('Claude credential has an invalid format')
    return kind, value


def billing_mode(kind):
    return {'api_key': 'anthropic_api', 'oauth': 'claude_subscription'}[kind]
