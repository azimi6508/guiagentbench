"""Pinned Cursor subscription runner configuration; no secret values."""

import json
from gui_agent_bench.codex_bridge import catalog
from gui_agent_bench.budgets import codex_budget
from gui_agent_bench.io import dump, digest, regular_file
from .registry import fingerprint

VERSION = '2026.10.22-27dcf5f'
CONTRACT = 'cursor-mcp-v1'
IMAGES = {role: 'gui-agent-bench-public-cursor-' + role + ':20261022-1' for role in ('agent', 'bridge', 'gateway')}
PROMPT = (
    'This is an unattended evaluation. Complete the public instruction below independently.\n'
    'Use only the bench MCP server. Paths under /workspace are virtual public files, accessed '
    'through bench_list_files, bench_read_file and bench_read_image; save submissions with '
    'bench_write_file. Discover the bench MCP tools if needed. Native shell, file, web, '
    'resource and subagent tools are unavailable.\n'
    'All permitted evidence is available; choose what to inspect. '
    'No follow-up user response will arrive. Save the requested submission.\n\n'
)


def budget(arm, timeout):
    limits = codex_budget(arm, timeout)
    return {
        **limits,
        'profile': 'cursor-bounded-v2',
        'relay_payload_requests': 4 * limits['bridge_calls'] + 128,
        'relay_heartbeat_requests': 4 * timeout + 128,
        'relay_metadata_requests': 4 * timeout + 128,
    }


def render(directory, spec, context):
    tools = [t['name'] for t in catalog(context.arm, context.platform, context.environment_profile)]
    instruction = regular_file(context.public_workspace / 'instruction.md', context.public_workspace, 65_536)
    if digest(instruction) != context.workspace_manifest['files']['instruction.md']:
        raise ValueError('Public instruction changed')
    policy = dict(
        schema=CONTRACT,
        model=spec.model,
        tools=tools,
        tool_names=['MCP:' + n for n in tools],
        instruction=PROMPT + instruction.decode('utf-8'),
    )
    dump(directory / 'agent.json', policy)
    dump(
        directory / 'cli-config.json',
        {
            'version': 1,
            'editor': {'vimMode': False},
            'permissions': {
                'allow': ['Mcp(bench:' + n + ')' for n in tools],
                'deny': ['Shell(*)', 'Read(*)', 'Write(*)', 'WebFetch(*)'],
            },
            'network': {'useHttp1ForAgent': True},
            'approvalMode': 'allowlist',
        },
    )
    dump(
        directory / 'mcp.json',
        {
            'mcpServers': {
                'bench': {
                    'command': '/usr/local/bin/python',
                    'args': ['/opt/bench/mcp_transport.py'],
                    'enabledTools': tools,
                }
            }
        },
    )
    events = ['preToolUse', 'beforeShellExecution', 'beforeReadFile', 'subagentStart', 'preCompact']
    dump(
        directory / 'hooks.json',
        {
            'version': 1,
            'hooks': {e: [{'command': '/usr/local/bin/python /opt/bench/guard.py ' + e, 'timeout': 5}] for e in events},
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
    lock = json.loads(regular_file(root / 'runtime/cursor/lock.json', root))
    if lock.get('version') != VERSION:
        raise ValueError('Cursor version differs')
    for name, sha in lock['files'].items():
        if digest(regular_file(root / name, root)) != sha:
            raise ValueError('Cursor source lock differs: ' + name)
    return lock


def qualification_path(root, spec):
    return root / 'runtime/cursor/qualifications' / (fingerprint(spec.record()) + '.json')


def resolved(root, specs, cells, images, timeout):
    return dict(
        schema='resolved-plan-v1',
        agents=[s.record() for s in specs],
        memberships=[{k: c[k] for k in ('task', 'arm', 'model', 'repeat') if k in c} for c in cells],
        images=images,
        runtime_lock=fingerprint(validate_lock(root)),
        runner_version=VERSION,
        protocol_contract=CONTRACT,
        billing_mode='cursor_account',
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
        provider_cost_usd=None,
    )
