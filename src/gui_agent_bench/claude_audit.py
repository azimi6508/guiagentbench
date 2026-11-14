"""Replay Claude Code isolation, MCP delivery and gateway evidence."""

import json
from pathlib import Path

from gui_agent_bench.codex_bridge import catalog
from gui_agent_bench.codex_audit import records
from gui_agent_bench.cursor_audit import reconcile as shared_reconcile
from gui_agent_bench.io import regular_file, same_source
from gui_agent_bench.materialize import validate_workspace

BASE_ENV = {
    'PATH',
    'HOME',
    'PYTHON_VERSION',
    'PYTHON_SHA256',
    'GPG_KEY',
    'LANG',
    'PYTHONDONTWRITEBYTECODE',
    'PYTHONUNBUFFERED',
}
# Fixed client configuration baked into the agent image (runtime/claude/Dockerfile).
AGENT_ENV = {
    'PATH': '/opt/claude:/usr/local/bin:/usr/bin:/bin',
    'HOME': '/run/home',
    'TMPDIR': '/run/tmp',
    'CLAUDE_CONFIG_DIR': '/run/home/.claude',
    'ANTHROPIC_BASE_URL': 'http://provider:8080',
    'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
    'DISABLE_AUTOUPDATER': '1',
    'DISABLE_TELEMETRY': '1',
    'DISABLE_ERROR_REPORTING': '1',
    'CLAUDE_CODE_MAX_RETRIES': '0',
    'ENABLE_TOOL_SEARCH': 'false',
    'DISABLE_AUTO_COMPACT': '1',
    'CLAUDE_CODE_DISABLE_AUTO_MEMORY': '1',
    'MAX_MCP_OUTPUT_TOKENS': '1000000',
    'MCP_TIMEOUT': '30000',
    'MCP_TOOL_TIMEOUT': '120000',
}
GATEWAY_ENV = {
    'GAB_CLAUDE_AUTH_KIND',
    'GAB_CLAUDE_MODEL',
    'GAB_CLAUDE_EFFORT',
    'GAB_CLAUDE_TOOLS',
    'GAB_CLAUDE_REQUEST_LIMIT',
    'GAB_CLAUDE_MODEL_IDENTITY',
}


def audit_isolation(details, networks, context):
    user = details['agent']['Config']['User']
    if ':' not in user or not all(v.isdecimal() and int(v) > 0 for v in user.split(':')):
        raise ValueError('Claude Code must run as a nonroot UID:GID')
    expected_mounts = {
        'agent': {'/policy': False, '/ipc': False},
        'bridge': {'/workspace': False, '/workspace/output': True, '/policy': False, '/audit': True, '/ipc': True},
        'gateway': {},
    }
    expected_networks = {
        'agent': {networks['inference']['Name']},
        'bridge': {'none'} if context.arm == 'judge_visual' else {networks['gui']['Name']},
        'gateway': {networks['inference']['Name'], 'bridge'},
    }
    expected_entries = {
        'agent': ['python', '/opt/bench/entrypoint.py'],
        'bridge': ['python', '-m', 'gui_agent_bench.codex_bridge'],
        'gateway': ['python', '/opt/bench/gateway.py'],
    }
    for role, item in details.items():
        host = item['HostConfig']
        security = ['no-new-privileges', 'apparmor=docker-default'] if role == 'agent' else ['no-new-privileges']
        if (
            not host['ReadonlyRootfs']
            or host['Privileged']
            or host.get('CapAdd')
            or host.get('CapDrop') != ['ALL']
            or host.get('SecurityOpt') != security
            or item.get('AppArmorProfile') != 'docker-default'
            or host.get('PidMode') == 'host'
            or host.get('IpcMode') == 'host'
            or host.get('NetworkMode') == 'host'
            or host.get('Memory', 0) <= 0
            or host.get('PidsLimit', 0) <= 0
            or item['Config']['User'] != user
            or host.get('RestartPolicy', {}).get('Name') not in {'no', ''}
        ):
            raise ValueError('Claude Code container isolation differs')
        mounts = {m['Destination']: m for m in item['Mounts'] if m['Type'] == 'bind'}
        if set(mounts) != set(expected_mounts[role]) or any(
            mounts[p]['RW'] != rw for p, rw in expected_mounts[role].items()
        ):
            raise ValueError('Claude Code mount allowlist differs')
        if any(m['Type'] not in {'bind', 'tmpfs'} for m in item['Mounts']):
            raise ValueError('Unexpected Claude Code volume')
        if set(item['NetworkSettings']['Networks']) != expected_networks[role]:
            raise ValueError('Claude Code network allowlist differs')
        if item['Config']['Entrypoint'] != expected_entries[role] or item['Config'].get('Cmd'):
            raise ValueError('Claude Code runtime command differs')
        env = dict(v.split('=', 1) for v in item['Config']['Env'])
        admitted = set(BASE_ENV)
        if role == 'agent':
            admitted |= set(AGENT_ENV)
            if any(env.get(k) != v for k, v in AGENT_ENV.items()) or item['Config']['WorkingDir'] != '/session':
                raise ValueError('Claude Code client configuration differs')
        elif role == 'bridge':
            admitted.add('PYTHONPATH')
        else:
            admitted |= GATEWAY_ENV
            if item.get('credential_environment_omitted') is not True:
                raise ValueError('Claude Code gateway credential projection missing')
            from gui_agent_bench.runners.claude_config import budget, tool_names, TOOL_PREFIX

            expected = {
                'GAB_CLAUDE_REQUEST_LIMIT': str(budget(context.arm, context.timeout_seconds)['model_requests']),
                'GAB_CLAUDE_TOOLS': ','.join(
                    TOOL_PREFIX + n for n in tool_names(context.arm, context.platform, context.environment_profile)
                ),
            }
            if any(env.get(k) != v for k, v in expected.items()) or env.get('GAB_CLAUDE_AUTH_KIND') not in {
                'api_key',
                'oauth',
            }:
                raise ValueError('Claude Code gateway policy differs')
        if set(env) - admitted:
            raise ValueError('Unexpected Claude Code environment')
    if any(not n['Internal'] for n in networks.values()):
        raise ValueError('Claude Code internal network differs')
    required = {
        'rw',
        'nosuid',
        'nodev',
        'size=512m',
        'mode=0700',
        'uid=' + user.split(':')[0],
        'gid=' + user.split(':')[1],
    }
    if set(details['agent']['HostConfig']['Tmpfs'].get('/run', '').split(',')) != required:
        raise ValueError('Claude Code tmpfs boundary differs')
    binds = {m['Destination']: m for m in details['agent']['Mounts'] if m['Type'] == 'bind'}
    if not same_source(binds['/policy']['Source'], context.config_directory):
        raise ValueError('Claude Code policy source differs')
    bridge_binds = {m['Destination']: m for m in details['bridge']['Mounts'] if m['Type'] == 'bind'}
    for name, path in {
        '/workspace': context.public_workspace,
        '/workspace/output': context.output_directory,
        '/policy': context.config_directory,
        '/audit': context.log_directory.parent / 'bridge',
    }.items():
        if not same_source(bridge_binds[name]['Source'], path):
            raise ValueError('Claude Code bridge source differs')
    if binds['/ipc']['Source'] != bridge_binds['/ipc']['Source']:
        raise ValueError('Claude Code transport source differs')
    validate_workspace(context.public_workspace, context.workspace_manifest)
    return dict(
        schema='claude-isolation-v1', status='pass', runner='claude', images={r: d['Image'] for r, d in details.items()}
    )


def reconcile(directory, policy, platform, *, broker_log=None):
    return shared_reconcile(
        directory,
        policy,
        platform,
        broker_log=broker_log,
        label='Claude Code',
        guard_event='PreToolUse',
        probe_methods=frozenset({'server/discover'}),
        request_meta=frozenset({'claudecode/toolUseId', 'progressToken'}),
    )


def audit_claude_authoring(directory, plan):
    from gui_agent_bench.runners.base import AuthoringContext
    from gui_agent_bench.runners.claude import validate_provider
    from gui_agent_bench.runners.claude_protocol import Session
    from gui_agent_bench.runners.cursor_logs import validate_streams
    from gui_agent_bench.io import strict_json

    def load(name):
        return json.loads(regular_file(directory / name, directory, 64_000_000))

    manifest = load('workspace-manifest.json')
    nets = load('claude-networks.json')
    agent_plan = load('agent-plan.json')
    context = AuthoringContext(
        directory.name,
        plan['arm'],
        plan['platform'],
        (1, 1),
        directory / 'workspace',
        manifest,
        directory / 'output',
        directory / 'config',
        directory / 'logs/agent',
        nets['gui']['Name'],
        None,
        agent_plan['budgets']['timeout_seconds'],
        manifest.get('environment_profile', 'generic'),
    )
    report = audit_isolation(load('claude-containers.json'), nets, context)
    policy = load('config/agent.json')
    if (
        policy['model'] != plan['agent_spec']['model']
        or policy['effort'] != plan['agent_spec']['reasoning_effort']
        or set(policy['tools'])
        != {t['name'] for t in catalog(context.arm, context.platform, context.environment_profile)}
    ):
        raise ValueError('Claude Code model/effort/catalog differs from plan')
    # Replay the complete client stream under the same rules used during capture.
    session = Session(policy, agent_plan['budgets'])
    for line in regular_file(directory / 'logs/agent/claude.ndjson', directory, 64_000_000).splitlines():
        if line.strip():
            session.event(strict_json(line))
    if not session.exited:
        raise ValueError('Claude Code stream did not complete')
    report.update(reconcile(directory, policy, plan['platform']))
    if (
        load('logs/agent/child.json') != {'exit_code': 0}
        or load('logs/agent/summary.json').get('completed') is not True
    ):
        raise ValueError('Claude Code did not complete')
    rows = validate_streams(
        directory / 'logs/claude-provider.ndjson',
        directory / 'logs/claude-provider-stderr.log',
        directory / 'logs/claude-provider-streams.json',
        contract='claude-provider-streams-v1',
    )
    requests = validate_provider(rows)
    if len(requests) > agent_plan['budgets']['model_requests']:
        raise ValueError('Claude Code request budget exceeded')
    report['model_requests'] = len(requests)
    return report, set(), set()
