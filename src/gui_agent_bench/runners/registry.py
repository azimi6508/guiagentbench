"""Fixed runner selection. Importing this module never imports MCP."""

import hashlib
import json
import re

from .base import AgentSpec


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


# Variants of the pinned OpenCode client that the relay admits. None keeps the client's default.
OPENCODE_VARIANTS = ('low', 'medium', 'high')


def resolve(identifier, *, reasoning_effort='medium', fixture_probe=False, variant=None):
    if not isinstance(identifier, str) or '/' not in identifier:
        raise ValueError(
            'Use reference/solution, fixture/scripted, openrouter/<model>, codex/<model>, cursor/<model> or claude/<model>'
        )
    prefix, model = identifier.split('/', 1)
    if not model or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]*', model):
        raise ValueError('An explicit valid model ID is required')
    if fixture_probe and identifier != 'fixture/scripted':
        raise ValueError('Isolation probes require fixture/scripted')
    if identifier == 'reference/solution':
        return AgentSpec(identifier, 'reference', model, 'none', None, 'reference-v1', 'reference-v1')
    if prefix == 'cursor':
        if model.lower() in {'auto', 'default'} or '/' in model or ':' in model or '..' in model:
            raise ValueError('Cursor requires an explicit model slug from agent models; Auto is unavailable')
        return AgentSpec(identifier, 'cursor', model, 'cursor_account', None, 'cursor-mcp-v1', 'cursor-bounded-v2')
    if prefix == 'claude':
        if not re.fullmatch(r'claude-[a-z0-9][a-z0-9.-]*', model) or '..' in model:
            raise ValueError(
                'Claude Code requires an explicit Anthropic model ID; aliases and default selection are unavailable'
            )
        if reasoning_effort not in {'low', 'medium', 'high', 'xhigh', 'max'}:
            raise ValueError('Unsupported Claude Code effort')
        return AgentSpec(
            identifier, 'claude', model, 'anthropic_credential', reasoning_effort, 'claude-mcp-v1', 'claude-bounded-v1'
        )
    if prefix == 'codex':
        if reasoning_effort not in {'low', 'medium', 'high', 'xhigh'}:
            raise ValueError('Unsupported Codex reasoning effort')
        return AgentSpec(identifier, 'codex', model, 'chatgpt', reasoning_effort, 'codex-mcp-v1', 'codex-bounded-v1')
    if prefix == 'openrouter' or identifier == 'fixture/scripted':
        if variant is not None and variant not in OPENCODE_VARIANTS:
            raise ValueError('Unsupported OpenCode variant')
        return AgentSpec(
            identifier,
            'opencode',
            model,
            'fixture' if prefix == 'fixture' else 'openrouter_api_key',
            variant,
            'opencode-v1',
            'opencode-v1',
        )
    raise ValueError('Unsupported model prefix')


def add_options(parser):
    from pathlib import Path

    parser.add_argument('--codex-auth-dir', type=Path, help='Dedicated saved ChatGPT login directory')
    parser.add_argument('--codex-reasoning-effort', choices=['low', 'medium', 'high', 'xhigh'], default='medium')
    parser.add_argument(
        '--cursor-auth-dir', type=Path, help='Dedicated Cursor CLI XDG login directory (or use CURSOR_API_KEY)'
    )
    parser.add_argument(
        '--claude-effort',
        choices=['low', 'medium', 'high', 'xhigh', 'max'],
        default='medium',
        help='Claude Code effort level (credentials: ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN)',
    )
    parser.add_argument(
        '--opencode-variant',
        choices=list(OPENCODE_VARIANTS),
        default=None,
        help='OpenCode model variant (reasoning effort) for openrouter/ and scripted models; default: none',
    )


ACCOUNT_RUNNERS = ('codex', 'cursor', 'claude')
BILLING_MODES = {'codex': 'chatgpt_subscription', 'cursor': 'cursor_account', 'claude': 'anthropic_credential'}


def effort(model, codex_effort='medium', claude_effort='medium'):
    """Select the effort option that applies to this model's runner."""
    return claude_effort if str(model).startswith('claude/') else codex_effort


def uses_opencode(model):
    return str(model).startswith('openrouter/') or model == 'fixture/scripted'


def spec_for(model, *, codex_effort='medium', claude_effort='medium', opencode_variant=None, fixture_probe=False):
    """Resolve a model with the one effort or variant option that applies to its runner."""
    return resolve(
        model,
        reasoning_effort=effort(model, codex_effort, claude_effort),
        fixture_probe=fixture_probe,
        variant=opencode_variant if uses_opencode(model) else None,
    )
