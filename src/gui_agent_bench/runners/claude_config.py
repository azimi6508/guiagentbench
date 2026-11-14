"""Pinned Claude Code runner configuration; no secret values."""

import json
from gui_agent_bench.codex_bridge import catalog
from gui_agent_bench.budgets import codex_budget, provider_requests, PROVIDER_REQUEST_BYTES
from gui_agent_bench.io import dump, digest, regular_file
from .registry import fingerprint

VERSION = '2.1.323'
CONTRACT = 'claude-mcp-v1'
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
IMAGES = {role: 'gui-agent-bench-public-claude-' + role + ':2.1.323-bench1' for role in ('agent', 'bridge', 'gateway')}
TOOL_PREFIX = 'mcp__bench__'
PROMPT = (
    'This is an unattended evaluation. Complete the public instruction below independently.\n'
    'Use only the bench MCP tools. Paths under /workspace are virtual public files, accessed '
    'through bench_list_files, bench_read_file and bench_read_image; save submissions with '
    'bench_write_file. Built-in shell, file, web, task and subagent tools are unavailable.\n'
    'All permitted evidence is available; choose what to inspect. '
    'No follow-up user response will arrive. Save the requested submission.\n\n'
)


def budget(arm, timeout):
    limits = codex_budget(arm, timeout)
    return {
        **limits,
        'profile': 'claude-bounded-v1',
        'model_requests': provider_requests(arm),
        'request_body_bytes': PROVIDER_REQUEST_BYTES,
    }


def tool_names(arm, platform, profile='generic'):
    return [t['name'] for t in catalog(arm, platform, profile)]


def render(directory, spec, context, auth_kind):
    if auth_kind not in {'api_key', 'oauth'}:
        raise ValueError('Unknown Claude credential kind')
    tools = tool_names(context.arm, context.platform, context.environment_profile)
    instruction = regular_file(context.public_workspace / 'instruction.md', context.public_workspace, 65_536)
    if digest(instruction) != context.workspace_manifest['files']['instruction.md']:
        raise ValueError('Public instruction changed')
    names = [TOOL_PREFIX + n for n in tools]
    policy = dict(
        schema=CONTRACT,
        model=spec.model,
        effort=spec.reasoning_effort,
        auth_kind=auth_kind,
        tools=tools,
        tool_names=names,
        instruction=PROMPT + instruction.decode('utf-8'),
    )
    dump(directory / 'agent.json', policy)
    dump(
        directory / 'mcp.json',
        {
            'mcpServers': {
                'bench': {
                    'type': 'stdio',
                    'command': '/usr/local/bin/python',
                    'args': ['/opt/bench/mcp_transport.py'],
                    'env': {},
                }
            }
        },
    )
    dump(
        directory / 'settings.json',
        {
            'permissions': {
                'allow': names,
                'deny': [
                    'Bash',
                    'Read',
                    'Write',
                    'Edit',
                    'MultiEdit',
                    'NotebookEdit',
                    'Glob',
                    'Grep',
                    'WebFetch',
                    'WebSearch',
                    'Task',
                    'Agent',
                ],
                'defaultMode': 'dontAsk',
            },
            'hooks': {
                'PreToolUse': [
                    {
                        'matcher': '*',
                        'hooks': [
                            {'type': 'command', 'command': '/usr/local/bin/python /opt/bench/guard.py', 'timeout': 5}
                        ],
                    }
                ]
            },
            'enableAllProjectMcpServers': False,
        },
    )
    dump(
        directory / 'bridge.json',
        dict(
            arm=context.arm,
            platform=context.platform,
            viewport=context.viewport,
            manifest=context.workspace_manifest,
            environment_profile=context.environment_profile,
        ),
    )
    return policy


def validate_lock(root):
    lock = json.loads(regular_file(root / 'runtime/claude/lock.json', root))
    if lock.get('version') != VERSION or lock.get('runner_contract') != CONTRACT:
        raise ValueError('Claude Code version differs')
    for name, sha in lock['files'].items():
        if digest(regular_file(root / name, root)) != sha:
            raise ValueError('Claude Code source lock differs: ' + name)
    return lock


def qualification_path(root, spec):
    return root / 'runtime/claude/qualifications' / (fingerprint(spec.record()) + '.json')


def resolved(root, specs, cells, images, timeout):
    return dict(
        schema='resolved-plan-v1',
        agents=[s.record() for s in specs],
        memberships=[{k: c[k] for k in ('task', 'arm', 'model', 'repeat') if k in c} for c in cells],
        images=images,
        runtime_lock=fingerprint(validate_lock(root)),
        runner_version=VERSION,
        protocol_contract=CONTRACT,
        billing_mode='anthropic_credential',
        budgets={a: budget(a, timeout) for a in {c['arm'] for c in cells}},
        task_hashes={
            c['task']: {
                p.relative_to(root / 'tasks' / c['task']).as_posix(): digest(p.read_bytes())
                for p in sorted((root / 'tasks' / c['task']).rglob('*'))
                if p.is_file() and '__pycache__' not in p.parts
            }
            for c in cells
        },
        automatic_trial_retries=False,
        automatic_fallback=False,
        client_request_retries=0,
        provider_cost_usd=None,
    )
