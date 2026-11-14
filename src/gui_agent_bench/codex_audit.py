"""Codex-specific boundaries and exact bridge/result correlation."""

import base64
from pathlib import Path

from gui_agent_bench.codex_bridge import META
from gui_agent_bench.io import digest, regular_file, same_source, strict_json
from gui_agent_bench.materialize import validate_workspace


def audit_isolation(details, networks, context, auth_file=None, ipc=None):
    from gui_agent_bench.runners.codex_security import audit as audit_security

    user = details['agent']['Config']['User']
    if ':' not in user or not all(x.isdecimal() and int(x) > 0 for x in user.split(':')):
        raise ValueError('Codex must run as a non-root host UID:GID')
    for role, item in details.items():
        audit_security(item, role)
        host = item['HostConfig']
        if (
            not host['ReadonlyRootfs']
            or host['Privileged']
            or host.get('CapAdd')
            or 'ALL' not in host['CapDrop']
            or 'no-new-privileges' not in host['SecurityOpt']
            or host.get('PidMode') == 'host'
            or host.get('IpcMode') == 'host'
            or item['Config']['User'] != user
            or host.get('Memory', 0) <= 0
            or host.get('PidsLimit', 0) <= 0
        ):
            raise ValueError('Codex container isolation differs')
        env = dict(e.split('=', 1) for e in item['Config']['Env'])
        admitted = {
            'PATH',
            'HOME',
            'CODEX_HOME',
            'PYTHONDONTWRITEBYTECODE',
            'PYTHONUNBUFFERED',
            'PYTHON_VERSION',
            'PYTHON_SHA256',
            'GPG_KEY',
            'LANG',
        }
        if role == 'agent':
            admitted |= {'HTTP_PROXY', 'HTTPS_PROXY'}
            if any(env.get(k) != 'http://egress:8080' for k in ('HTTP_PROXY', 'HTTPS_PROXY')):
                raise ValueError('Unexpected Codex proxy')
            if (
                env.get('HOME') != '/run/home'
                or env.get('CODEX_HOME') != '/run/codex'
                or item['Config']['WorkingDir'] != '/session'
            ):
                raise ValueError('Codex runtime home differs')
        if role == 'bridge':
            admitted.add('PYTHONPATH')
        if set(env) - admitted:
            raise ValueError('Unexpected Codex environment')
        mounts = {m['Destination']: m for m in item['Mounts'] if m['Type'] == 'bind'}
        expected = {
            'agent': {'/config': False, '/auth-input/auth.json': False, '/ipc': False},
            'bridge': {'/workspace': False, '/workspace/output': True, '/policy': False, '/audit': True, '/ipc': True},
            'egress': {},
        }[role]
        if set(mounts) != set(expected) or any(m['RW'] != expected[d] for d, m in mounts.items()):
            raise ValueError('Codex mount boundary differs')
        if any(m['Type'] not in {'bind', 'tmpfs'} for m in item['Mounts']):
            raise ValueError('Unexpected Codex volume')
        expected_networks = {
            'agent': {networks['inference']['Name']},
            'bridge': {'none'} if context.arm == 'judge_visual' else {networks['gui']['Name']},
            'egress': {networks['inference']['Name'], 'bridge'},
        }[role]
        if set(item['NetworkSettings']['Networks']) != expected_networks:
            raise ValueError('Codex network boundary differs')
        expected_entry = {
            'agent': ['/usr/local/bin/python', '/opt/bench/entrypoint.py'],
            'bridge': ['python', '-m', 'gui_agent_bench.codex_bridge'],
            'egress': ['python', '/opt/bench/egress_proxy.py'],
        }[role]
        if item['Config']['Entrypoint'] != expected_entry or item['Config'].get('Cmd'):
            raise ValueError('Unexpected Codex command')
    for network in networks.values():
        if not network['Internal']:
            raise ValueError('Codex internal network differs')
    mounts = {m['Destination']: m for m in details['agent']['Mounts'] if m['Type'] == 'bind'}
    expected = {'/config': context.config_directory, '/auth-input/auth.json': auth_file, '/ipc': ipc}
    for path, source in expected.items():
        if source is not None and not same_source(mounts[path]['Source'], source):
            raise ValueError('Codex mount source differs')
    uid, gid = user.split(':')
    tmpfs = details['agent']['HostConfig']['Tmpfs']
    for name, size in [('/run/codex', '512m'), ('/run/home', '16m'), ('/run/control', '1m')]:
        required = {'rw', 'nosuid', 'nodev', 'size=' + size, 'mode=0700', 'uid=' + uid, 'gid=' + gid}
        if set(tmpfs.get(name, '').split(',')) != required:
            raise ValueError('Codex tmpfs boundary differs')
    validate_workspace(context.public_workspace, context.workspace_manifest)
    return {
        'schema': 'codex-isolation-v1',
        'status': 'pass',
        'runner': 'codex',
        'images': {r: d['Image'] for r, d in details.items()},
        'network_roles': {r: n['Name'] for r, n in networks.items()},
    }


def records(path, limit=64_000_000):
    used = 0
    with path.open('rb') as stream:
        for line in stream:
            used += len(line)
            if used > limit or not line.endswith(b'\n'):
                raise ValueError('Incomplete Codex evidence')
            yield strict_json(line)


def operation_failure(item, bridge, broker_log=None):
    """Recover operator details only from an unambiguous trusted broker match.

    The public result intentionally carries no private diagnostic metadata. Match
    repeated requests by occurrence, requiring equal complete request counts in
    both ledgers; never select a convenient failure by its cause alone. This is
    reporting only: it cannot change the cause or admit a failed operation.
    """
    from gui_agent_bench.failures import Failure, result_cause
    from gui_agent_bench.failure_detail import restore

    error = Failure(result_cause(item['result']) or 'unknown_operation_error')
    if not item['tool'].startswith('gui_'):
        return error
    try:
        calls = [
            r
            for r in records(bridge / 'bridge.ndjson')
            if r.get('phase') == 'completed'
            and r.get('tool') == item['tool']
            and r.get('arguments') == item['arguments']
        ]
        indexes = [i for i, r in enumerate(calls) if r.get('bridge_call_id') == item['bridge_call_id']]
        # During live authoring, cleanup has not exported browser.ndjson yet.
        # Read the current trusted container log without changing stored evidence
        # or the authoring evidence budget; cleanup still performs its export.
        if broker_log is None:
            raw = regular_file(bridge.parent / 'browser.ndjson', bridge.parent, 64_000_000)
        else:
            raw = broker_log().encode('utf-8')
            if len(raw) > 64_000_000:
                return error
        broker_rows = (strict_json(line) for line in raw.splitlines())
        observed = [
            r for r in broker_rows if r.get('tool') == item['tool'][4:] and r.get('arguments') == item['arguments']
        ]
        if len(indexes) != 1 or len(calls) != len(observed):
            return error
        row = observed[indexes[0]]
        failure = row.get('failure', {})
        if (
            row.get('operation_failed') is True
            and row.get('denied') is False
            and failure.get('version') == 'failure-v1'
            and failure.get('cause') == error.cause
            and failure.get('phase') == 'authoring'
            and 'detail' in failure
        ):
            restore(error, failure['detail'])
    except Exception:
        # Missing/old/ambiguous detail never replaces the original fatal cause.
        pass
    return error


def reconcile(agent, bridge, tools, platform=None, *, broker_log=None):
    allowed = {t['name'] for t in tools}
    calls, completed, images = {}, {}, set()
    recoveries = []
    for item in records(bridge / 'bridge.ndjson'):
        call_id = item['bridge_call_id']
        if item['phase'] == 'started':
            if call_id in calls:
                raise ValueError('Duplicate bridge call')
            calls[call_id] = item
        elif item['phase'] == 'completed':
            if call_id not in calls or call_id in completed:
                raise ValueError('Bridge call completion differs')
            if item['arguments'] != calls[call_id]['arguments'] or item['tool'] != calls[call_id]['tool']:
                raise ValueError('Bridge operation failed or changed')
            result = item['result']
            from gui_agent_bench.authoring_recovery import recovery_from_result

            recovered = recovery_from_result(result, platform, item['tool'])
            from gui_agent_bench.failures import authoring_feedback

            feedback = authoring_feedback(result, item['tool'])
            if 'recovery' in item or item.get('operation_failed'):
                if (
                    feedback
                    and 'recovery' not in item
                    and item.get('operation_failed') is True
                    and item.get('denied') is False
                ):
                    pass
                elif (
                    not recovered
                    or recovered != item.get('recovery')
                    or recovered['sequence'] != len(recoveries) + 1
                    or item.get('operation_failed') is not True
                    or item.get('denied') is not False
                ):
                    raise operation_failure(item, bridge, broker_log)
                else:
                    recoveries.append(recovered)
            elif recovered:
                raise ValueError('Unrecorded authoring recovery')
            for block in result['content']:
                if block['type'] == 'image':
                    sha = block['sha256']
                    if block['blob'] != 'images/' + sha + '.png' or len(sha) != 64:
                        raise ValueError('Invalid image blob')
                    data = regular_file(bridge / block['blob'], bridge)
                    if digest(data) != sha or len(data) != block['bytes']:
                        raise ValueError('Bridge image changed')
                    block.clear()
                    block.update(type='image', mimeType='image/png', data=base64.b64encode(data).decode())
                    images.add(sha)
            completed[call_id] = item
        else:
            raise ValueError('Unknown bridge phase')
    if set(calls) != set(completed):
        raise ValueError('In-flight bridge call')
    seen, raw_refs, tool_items = set(), set(), {}
    terminal = False
    hook_starts, hook_ends = set(), set()
    for record in records(agent / 'codex-rpc.ndjson'):
        raw_refs.add(record['sequence'])
        if record.get('privacy_projection'):
            continue
        value = strict_json(base64.b64decode(record['frame_base64'], validate=True))
        if record['direction'] != 'in':
            continue
        method, params = value.get('method'), value.get('params') or {}
        if method in {'model/rerouted', 'thread/compacted', 'error'}:
            raise ValueError('Fatal Codex lifecycle event')
        if method == 'hook/started':
            hook_starts.add(params['run']['id'])
        if method == 'hook/completed':
            run = params['run']
            if run['eventName'] != 'preToolUse' or run['status'] != 'completed':
                raise ValueError('Required hook failed')
            hook_ends.add(run['id'])
        if method == 'turn/completed':
            if terminal or params['turn']['status'] != 'completed' or params['turn'].get('error') is not None:
                raise ValueError('Codex turn failed')
            terminal = True
        if method not in {'item/started', 'item/completed'}:
            continue
        item = params['item']
        if item['type'] not in {'userMessage', 'agentMessage', 'reasoning', 'mcpToolCall'}:
            raise ValueError('Forbidden native item')
        if item['type'] != 'mcpToolCall':
            continue
        identifier = item['id']
        if method == 'item/started':
            if identifier in tool_items:
                raise ValueError('Duplicate Codex tool start')
            tool_items[identifier] = False
            continue
        if identifier not in tool_items or tool_items[identifier]:
            raise ValueError('Unexpected Codex tool completion')
        tool_items[identifier] = True
        result = item.get('result') or {}
        call_id = result.get('_meta', {}).get(META)
        if call_id in seen or call_id not in completed:
            raise ValueError('Codex/bridge result bijection failed')
        original = completed[call_id]
        if (
            item.get('server') != 'bench'
            or item.get('tool') != original['tool']
            or item.get('tool') not in allowed
            or item.get('arguments') != original['arguments']
            or result.get('content') != original['result']['content']
            or item.get('status') != ('failed' if original['result'].get('isError') else 'completed')
            or item.get('error') is not None
        ):
            raise ValueError('Codex/bridge content differs')
        seen.add(call_id)
    if (
        not terminal
        or seen != set(completed)
        or not all(tool_items.values())
        or hook_starts != hook_ends
        or (tool_items and not hook_ends)
    ):
        raise ValueError('Incomplete Codex lifecycle')
    for event in records(agent / 'normalized.ndjson'):
        if (
            event.get('schema') != 'codex-event-v1'
            or not event.get('raw_refs')
            or not set(event['raw_refs']) <= raw_refs
        ):
            raise ValueError('Forged normalized Codex reference')
    return {
        'status': 'pass',
        'bridge_calls': len(completed),
        'images': sorted(images),
        'authoring_recoveries': recoveries,
    }


def audit_codex_authoring(root, plan):
    from gui_agent_bench.runners.base import AuthoringContext
    from gui_agent_bench.codex_bridge import catalog

    def load(name):
        return strict_json(regular_file(root / name, root))

    manifest = load('workspace-manifest.json')
    profile = 'native_extended' if plan['task'].startswith('mobile/native_extended-') else 'generic'
    if manifest.get('environment_profile', 'generic') != profile:
        raise ValueError('Codex environment profile differs from task')
    if load('config/bridge.json').get('environment_profile', 'generic') != profile:
        raise ValueError('Codex bridge profile differs from task')
    startup = load('logs/agent/startup.json')
    summary = load('logs/agent/summary.json')
    if plan.get('runner_version') != '0.162.0' or startup.get('status') != 'passed' or not summary.get('completed'):
        raise ValueError('Codex authoring is not qualified and complete')
    if summary.get('provider_cost_usd') is not None or summary.get('billing_mode') != 'chatgpt_subscription':
        raise ValueError('Codex billing record differs')
    nets = load('codex-networks.json')
    context = AuthoringContext(
        root.name,
        manifest['arm'],
        manifest['platform'],
        (0, 0),
        root / 'workspace',
        manifest,
        root / 'output',
        root / 'config',
        root / 'logs/agent',
        nets['gui']['Name'],
        None,
        3600,
    )
    report = audit_isolation(load('codex-containers.json'), nets, context)
    report.update(
        reconcile(
            root / 'logs/agent',
            root / 'logs/bridge',
            catalog(manifest['arm'], manifest['platform'], profile),
            manifest['platform'],
        )
    )
    if (
        startup['model'] != plan['agent_spec']['model']
        or startup['reasoning_effort'] != plan['agent_spec']['reasoning_effort']
    ):
        raise ValueError('Codex model identity differs')
    if any(not item.get('removed') for item in load('cleanup.json')):
        raise ValueError('Codex resource cleanup incomplete')
    return report, set(), set()
