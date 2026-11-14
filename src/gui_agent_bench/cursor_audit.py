"""Replay Cursor isolation and exact single-session MCP delivery evidence."""

import base64
import json
from pathlib import Path

from gui_agent_bench.codex_bridge import catalog, META
from gui_agent_bench.codex_audit import records, operation_failure
from gui_agent_bench.io import regular_file, digest, same_source, strict_json
from gui_agent_bench.materialize import validate_workspace


def audit_isolation(details, networks, context):
    user = details['agent']['Config']['User']
    if ':' not in user or not all(v.isdecimal() and int(v) > 0 for v in user.split(':')):
        raise ValueError('Cursor must run as a nonroot UID:GID')
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
            raise ValueError('Cursor container isolation differs')
        mounts = {m['Destination']: m for m in item['Mounts'] if m['Type'] == 'bind'}
        if set(mounts) != set(expected_mounts[role]) or any(
            mounts[p]['RW'] != rw for p, rw in expected_mounts[role].items()
        ):
            raise ValueError('Cursor mount allowlist differs')
        if any(m['Type'] not in {'bind', 'tmpfs'} for m in item['Mounts']):
            raise ValueError('Unexpected Cursor volume')
        if set(item['NetworkSettings']['Networks']) != expected_networks[role]:
            raise ValueError('Cursor network allowlist differs')
        if item['Config']['Entrypoint'] != expected_entries[role] or item['Config'].get('Cmd'):
            raise ValueError('Cursor runtime command differs')
        env = dict(v.split('=', 1) for v in item['Config']['Env'])
        admitted = {
            'PATH',
            'HOME',
            'PYTHON_VERSION',
            'PYTHON_SHA256',
            'GPG_KEY',
            'LANG',
            'PYTHONDONTWRITEBYTECODE',
            'PYTHONUNBUFFERED',
        }
        if role == 'agent':
            admitted |= {'XDG_CONFIG_HOME', 'CURSOR_CONFIG_DIR'}
            if (
                env.get('HOME') != '/run/home'
                or env.get('XDG_CONFIG_HOME') != '/run/xdg'
                or env.get('CURSOR_CONFIG_DIR') != '/run/home/.cursor'
                or item['Config']['WorkingDir'] != '/session'
            ):
                raise ValueError('Cursor session home differs')
        elif role == 'bridge':
            admitted.add('PYTHONPATH')
        else:
            admitted |= {
                'GAB_CURSOR_REQUEST_LIMIT',
                'GAB_CURSOR_PAYLOAD_LIMIT',
                'GAB_CURSOR_HEARTBEAT_LIMIT',
                'GAB_CURSOR_METADATA_LIMIT',
                'GAB_CURSOR_MODEL',
                'GAB_CURSOR_MODEL_IDENTITY',
                'GAB_CURSOR_IDENTITY_PROBE',
            }
            if item.get('credential_environment_omitted') is not True:
                raise ValueError('Cursor gateway credential projection missing')
            protocol_keys = {'GAB_CURSOR_PAYLOAD_LIMIT', 'GAB_CURSOR_HEARTBEAT_LIMIT', 'GAB_CURSOR_METADATA_LIMIT'}
            if protocol_keys & set(env):
                from gui_agent_bench.runners.cursor_config import budget

                limits = budget(context.arm, context.timeout_seconds)
                expected = {
                    'GAB_CURSOR_PAYLOAD_LIMIT': str(limits['relay_payload_requests']),
                    'GAB_CURSOR_HEARTBEAT_LIMIT': str(limits['relay_heartbeat_requests']),
                    'GAB_CURSOR_METADATA_LIMIT': str(limits['relay_metadata_requests']),
                }
                if any(env.get(k) != v for k, v in expected.items()) or 'GAB_CURSOR_REQUEST_LIMIT' in env:
                    raise ValueError('Cursor protocol budget differs')
        if set(env) - admitted:
            raise ValueError('Unexpected Cursor environment')
    if any(not n['Internal'] for n in networks.values()):
        raise ValueError('Cursor internal network differs')
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
        raise ValueError('Cursor tmpfs boundary differs')
    binds = {m['Destination']: m for m in details['agent']['Mounts'] if m['Type'] == 'bind'}
    if not same_source(binds['/policy']['Source'], context.config_directory):
        raise ValueError('Cursor policy source differs')
    bridge_binds = {m['Destination']: m for m in details['bridge']['Mounts'] if m['Type'] == 'bind'}
    for name, path in {
        '/workspace': context.public_workspace,
        '/workspace/output': context.output_directory,
        '/policy': context.config_directory,
        '/audit': context.log_directory.parent / 'bridge',
    }.items():
        if not same_source(bridge_binds[name]['Source'], path):
            raise ValueError('Cursor bridge source differs')
    if binds['/ipc']['Source'] != bridge_binds['/ipc']['Source']:
        raise ValueError('Cursor transport source differs')
    validate_workspace(context.public_workspace, context.workspace_manifest)
    return dict(
        schema='cursor-isolation-v1', status='pass', runner='cursor', images={r: d['Image'] for r, d in details.items()}
    )


def reconcile(
    directory,
    policy,
    platform,
    *,
    broker_log=None,
    label='Cursor',
    guard_event='preToolUse',
    probe_methods=frozenset(),
    request_meta=frozenset(),
):
    """Replay bridge/MCP delivery; shared by the Cursor and Claude Code runners.

    ``probe_methods`` are client capability probes that the bridge must answer
    with an error and that never reach a tool. ``request_meta`` lists the only
    client ``_meta`` keys admitted on tools/call; the remaining params must equal
    the trusted bridge record exactly.
    """
    folder = directory / 'logs/agent'
    bridge = directory / 'logs/bridge'
    allowed = set(policy['tools'])
    started, completed = {}, {}
    recoveries = []
    for row in records(bridge / 'bridge.ndjson'):
        key = row['bridge_call_id']
        if row['phase'] == 'started':
            if key in started or row['tool'] not in allowed:
                raise ValueError(f'Unexpected {label} bridge call')
            started[key] = row
        elif row['phase'] == 'completed':
            if key not in started or key in completed:
                raise ValueError(f'Unexpected {label} bridge completion')
            first = started[key]
            if any(row[k] != first[k] for k in ('tool', 'arguments', 'mcp_request_id')):
                raise ValueError(f'{label} bridge call changed')
            from gui_agent_bench.failures import authoring_feedback

            if row.get('operation_failed'):
                from gui_agent_bench.authoring_recovery import recovery_from_result

                recovery = recovery_from_result(row['result'], platform, row['tool'])
                if recovery and recovery == row.get('recovery') and recovery['sequence'] == len(recoveries) + 1:
                    recoveries.append(recovery)
                elif not authoring_feedback(row['result'], row['tool']):
                    raise operation_failure(row, bridge, broker_log)
            completed[key] = row
        else:
            raise ValueError(f'Unknown {label} bridge phase')
    if started.keys() != completed.keys():
        raise ValueError(f'Incomplete {label} bridge calls')
    requests, delivered = {}, set()
    tool_catalog = False
    for envelope in records(folder / 'mcp.ndjson'):
        value = strict_json(base64.b64decode(envelope['frame_base64'], validate=True))
        if envelope['direction'] == 'out':
            if 'id' in value:
                if value['id'] in requests:
                    raise ValueError(f'Duplicate {label} MCP request')
                requests[value['id']] = value
            if value.get('method') not in {
                'initialize',
                'notifications/initialized',
                'tools/list',
                'tools/call',
                'ping',
            } | set(probe_methods):
                raise ValueError(f'Unexpected {label} MCP request')
        elif envelope['direction'] == 'in':
            request = requests.get(value.get('id'))
            if request is not None and request.get('method') in probe_methods:
                if 'error' not in value or 'result' in value:
                    raise ValueError(f'Unexpected {label} MCP probe response')
                continue
            if request is None or 'error' in value:
                raise ValueError(f'Unexpected {label} MCP response')
            if request['method'] == 'tools/list':
                if {t['name'] for t in value['result']['tools']} != allowed:
                    raise ValueError(f'{label} MCP catalog differs')
                tool_catalog = True
            if request['method'] != 'tools/call':
                continue
            result = value['result']
            key = result.get('_meta', {}).get(META)
            if key in delivered or key not in completed:
                raise ValueError(f'{label} tool result correlation differs')
            row = completed[key]
            params = dict(request['params'])
            meta = params.pop('_meta', None) if request_meta else None
            if meta is not None and (not isinstance(meta, dict) or set(meta) - set(request_meta)):
                raise ValueError(f'{label} tool request metadata differs')
            if params != {'name': row['tool'], 'arguments': row['arguments']} or value['id'] != row['mcp_request_id']:
                raise ValueError(f'{label} tool request differs')
            expected = json.loads(json.dumps(row['result']))
            for block in expected['content']:
                if block['type'] == 'image':
                    data = regular_file(bridge / block['blob'], bridge)
                    if digest(data) != block['sha256'] or len(data) != block['bytes']:
                        raise ValueError(f'{label} image evidence differs')
                    block.clear()
                    block.update(type='image', mimeType='image/png', data=base64.b64encode(data).decode())
            if expected != result:
                raise ValueError(f'{label} MCP result changed or truncated')
            delivered.add(key)
        else:
            raise ValueError(f'Unknown {label} transport direction')
    if (completed and not tool_catalog) or delivered != set(completed):
        raise ValueError(f'{label} tools/results were not completely delivered')
    for row in records(folder / 'guard.ndjson'):
        if row.get('allowed') is not True or row.get('event') != guard_event:
            raise ValueError(f'{label} attempted a forbidden native capability')
    return {'authoring_recoveries': recoveries, 'delivered_tools': len(delivered)}


def validate_provider_records(provider):
    """Replay the reviewed success contract; every denial remains fatal."""
    from gui_agent_bench.runners.cursor import provider_record_success

    provider = list(provider)
    if (
        not provider
        or not all(provider_record_success(row) for row in provider)
        or all(row.get('outcome') == 'client_closed_before_request' for row in provider)
    ):
        raise ValueError('Cursor provider failed or denied a request')
    captured = None
    generation = 0
    for row in provider:
        snapshot = row.get('privacy_snapshot')
        if snapshot is None:
            continue
        binding = tuple(snapshot[k] for k in ('generation', 'request_sha256', 'response_sha256'))
        if snapshot['event'] == 'captured':
            if snapshot['generation'] != generation + 1:
                raise ValueError('Privacy snapshot capture order differs')
            generation = snapshot['generation']
            captured = binding
        elif binding != captured:
            raise ValueError('Privacy cache lacks the current successful upstream capture')


def audit_cursor_authoring(directory, plan):
    from gui_agent_bench.runners.base import AuthoringContext

    def load(name):
        return json.loads(regular_file(directory / name, directory, 64_000_000))

    manifest = load('workspace-manifest.json')
    nets = load('cursor-networks.json')
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
    report = audit_isolation(load('cursor-containers.json'), nets, context)
    policy = load('config/agent.json')
    if policy['model'] != plan['agent_spec']['model'] or set(policy['tools']) != {
        t['name'] for t in catalog(context.arm, context.platform, context.environment_profile)
    }:
        raise ValueError('Cursor model/catalog differs from plan')
    report.update(reconcile(directory, policy, plan['platform']))
    if (
        load('logs/agent/child.json') != {'exit_code': 0}
        or load('logs/agent/summary.json').get('completed') is not True
    ):
        raise ValueError('Cursor did not complete')
    from gui_agent_bench.runners.cursor_logs import CONTRACT, validate_streams

    if agent_plan.get('provider_log_contract') == CONTRACT:
        provider = validate_streams(
            directory / 'logs/cursor-provider.ndjson',
            directory / 'logs/cursor-provider-stderr.log',
            directory / 'logs/cursor-provider-streams.json',
        )
    else:
        if agent_plan.get('provider_log_contract') is not None:
            raise ValueError('Unknown provider stream evidence contract')
        stderr_path = directory / 'logs/cursor-provider-stderr.log'
        if stderr_path.exists() and regular_file(stderr_path, directory, 64_000_000):
            raise ValueError('Unexpected gateway stderr')
        provider = list(records(directory / 'logs/cursor-provider.ndjson'))
    validate_provider_records(provider)
    return report, set(), set()
