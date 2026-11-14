"""Audit recorded workspace, process, application and network boundaries."""

from pathlib import Path
import json
from gui_agent_bench.materialize import validate_workspace
from gui_agent_bench.io import digest, recorded_evidence, regular_file, same_source
from gui_agent_bench.arms import ARM_IDS, generated, artifact_name


def audit_agent(details: dict, workspace: Path, manifest: dict, config: dict, network: dict) -> dict:
    validate_workspace(workspace, manifest)
    host = details['HostConfig']
    if not host['ReadonlyRootfs'] or host['Privileged'] or 'ALL' not in host['CapDrop']:
        raise ValueError('agent container isolation is weaker than required')
    if not any((flag.startswith('no-new-privileges') for flag in host['SecurityOpt'])):
        raise ValueError('agent can acquire new privileges')
    if details['Config']['User'] != 'node' or host.get('PidMode') == 'host' or host.get('IpcMode') == 'host':
        raise ValueError('agent user/process namespace is not isolated')
    if not network['Internal'] or len(details['NetworkSettings']['Networks']) != 1:
        raise ValueError('agent network is not dedicated/internal')
    mounts = {mount['Destination']: mount for mount in details['Mounts'] if mount['Type'] == 'bind'}
    if set(mounts) != {'/workspace', '/workspace/output', '/config'}:
        raise ValueError('unexpected agent bind mount')
    if any((item['Type'] != 'bind' for item in details['Mounts'])):
        raise ValueError('unexpected agent volume')
    for destination, source in {
        '/workspace': workspace,
        '/workspace/output': workspace.parent / 'output',
        '/config': workspace.parent / 'config',
    }.items():
        if not same_source(mounts[destination]['Source'], source):
            raise ValueError('agent bind source differs from isolated trial path')
    if mounts['/workspace']['RW'] or mounts['/config']['RW'] or (not mounts['/workspace/output']['RW']):
        raise ValueError('incorrect read/write mount boundary')
    for entry in details['Config']['Env']:
        if any((term in entry.split('=', 1)[0].upper() for term in ('API_KEY', 'TOKEN', 'VARIANT', 'LABEL', 'REWARD'))):
            raise ValueError('secret or private metadata in agent container environment')
    permission = config['permission']
    if permission['*'] != 'deny' or permission['bash'] != 'deny' or permission['task'] != 'deny':
        raise ValueError('unexpected execution/delegation permissions')
    expected_reads = {
        '*': 'deny',
        'workspace/output/*': 'allow',
        **{'workspace/' + path: 'allow' for path in manifest['files']},
    }
    arm = manifest['arm']
    platform = manifest.get('platform', 'web')
    if arm == 'judge_visual':
        expected_reads = {key: value for key, value in expected_reads.items() if not key.endswith('.png')}
        expected_reads['workspace/evidence/screenshots/*.png'] = 'allow'
    if permission.get('read') != expected_reads or permission.get('edit') != {
        '*': 'deny',
        'workspace/output/*': 'allow',
    }:
        raise ValueError('effective file permissions exceed the workspace allowlist')
    allowed_tools = {key for key, value in permission.items() if value == 'allow'}
    if arm == 'judge_visual':
        if config['mcp'] or allowed_tools:
            raise ValueError('judge_visual cannot access the live app')
    elif arm in ARM_IDS:
        expected_tools = {'gui_observe', 'gui_reset', 'gui_open_url', 'gui_step'}
        if not arm.endswith('_visual'):
            expected_tools.add('gui_dump_ui')
        if platform == 'tv':
            expected_tools -= {'gui_dump_ui', 'gui_open_url'}
        expected_mcp = {
            'gui': {
                'type': 'remote',
                'url': 'http://browser:8081/mcp',
                'enabled': True,
                'oauth': False,
                'headers': {'Connection': 'close'},
            }
        }
        if config['mcp'] != expected_mcp or allowed_tools != expected_tools:
            raise ValueError('unexpected live tools')
    else:
        raise ValueError('unimplemented arm')
    return {
        'status': 'pass',
        'scope': f'{arm} Docker mounts, workspace hashes, configuration and network',
        'runtime_verified': True,
        'other_arms_verified': False,
        'public_file_count': len(manifest['files']),
        'agent_image_id': details['Image'],
    }


def audit_fixture_provider(details, folder, network):
    """Private scripted solutions belong solely to the trusted fixture helper."""
    host = details['HostConfig']
    binds = [m for m in details['Mounts'] if m['Type'] != 'tmpfs']
    if (
        not host['ReadonlyRootfs']
        or host['Privileged']
        or host.get('CapAdd')
        or set(host.get('CapDrop') or []) != {'ALL'}
        or 'no-new-privileges' not in host['SecurityOpt']
        or set(details['NetworkSettings']['Networks']) != {network}
        or len(binds) != 1
        or binds[0]['Type'] != 'bind'
        or binds[0]['RW']
        or binds[0]['Destination'] != '/fixture-control.json'
        or not same_source(binds[0]['Source'], folder / 'fixture-control.json')
        or any(
            any(term in entry.split('=', 1)[0].upper() for term in ('API_KEY', 'TOKEN', 'SECRET'))
            for entry in details['Config']['Env']
        )
    ):
        raise ValueError('Scripted fixture provider boundary differs')
    from gui_agent_bench.reference_controls import validate_record

    validate_record(json.loads(regular_file(folder / 'fixture-control.json', folder)))
    return {'status': 'pass', 'trusted_fixture_only': True}


def audit_broker(details: dict, agent_network: str, app_network: str, setup_source=None, references=None) -> dict:
    host = details['HostConfig']
    binds = [m for m in details['Mounts'] if m['Type'] != 'tmpfs']
    expected = {}
    if setup_source is not None:
        expected['/setup/source.py'] = Path(setup_source)
    if references is not None:
        expected['/references'] = Path(references)
    if len(binds) != len(expected) or any(
        (
            m['Type'] != 'bind'
            or m['RW']
            or m['Destination'] not in expected
            or not same_source(m['Source'], expected[m['Destination']])
            for m in binds
        )
    ):
        raise ValueError('broker mounts exceed trusted setup and sealed image references')
    if set(details['NetworkSettings']['Networks']) != {agent_network, app_network}:
        raise ValueError('broker network boundary differs')
    if (
        not host['ReadonlyRootfs']
        or host['Privileged']
        or 'ALL' not in host['CapDrop']
        or (details['Config']['User'] != 'pwuser')
    ):
        raise ValueError('broker isolation differs')
    if any(
        (
            any((term in e.split('=', 1)[0].upper() for term in ('API_KEY', 'TOKEN', 'VARIANT', 'LABEL', 'REWARD')))
            for e in details['Config']['Env']
        )
    ):
        raise ValueError('secret in browser broker')
    return {'status': 'pass', 'task_mounts': int(setup_source is not None), 'direct_internet': False}


def audit_application(task, folder, platform=None):
    """Apply the environment boundary independently of the authoring runner."""
    platform = platform or task.split('/')[0]
    if platform == 'mobile':
        from gui_agent_bench.mobile_audit import audit_mobile

        return audit_mobile(folder)
    if platform == 'tv':
        from gui_agent_bench.tv_session import audit_app

        return {'application_boundary': audit_app(folder)}
    from gui_agent_bench.applications import audit_app

    return {'application_boundary': audit_app(folder)}


def audit_run(directory: Path, require_probes: bool = False) -> dict:
    """Audit a recorded run, which may have been moved since it was recorded."""
    with recorded_evidence():
        return _audit_run(directory, require_probes)


def _audit_run(directory: Path, require_probes: bool = False) -> dict:
    plan = json.loads(regular_file(directory / 'plan.json', directory))
    if plan.get('reference') is True or plan.get('model') == 'reference/solution':
        from gui_agent_bench.reference_audit import audit_reference

        return audit_reference(directory, require_probes)
    if plan['arm'] not in ARM_IDS or plan['planned_trials'] != len(plan['trials']):
        raise ValueError('invalid judge plan')
    reports = []
    forbidden = {
        '/fixture-control.json',
        '/control.json',
        '/private/labels.json',
        '/config/opencode.json',
        '/workspace/escape.txt',
        '/workspace/output/../escape.txt',
    }
    for trial in plan['trials']:
        if len(trial['id']) != 16 or any((ch not in '0123456789abcdef' for ch in trial['id'])):
            raise ValueError('invalid trial ID')
        root = directory / 'trials' / trial['id']

        def load(name):
            return json.loads(regular_file(root / name, root))

        runner = plan.get('runner', 'opencode')
        if runner == 'codex':
            if require_probes:
                raise ValueError('Use the versioned Codex qualifier; OpenCode probes do not apply')
            from gui_agent_bench.codex_audit import audit_codex_authoring

            report, denied, observed_images = audit_codex_authoring(root, plan)
            manifest = load('workspace-manifest.json')
            if manifest['arm'] != plan['arm'] or manifest['platform'] != plan.get('platform'):
                raise ValueError('Codex workspace differs from plan')
            if plan['arm'] != 'judge_visual':
                roles = load('codex-networks.json')
                audit_broker(
                    load('broker-container.json'),
                    roles['gui']['Name'],
                    roles['capture']['Name'],
                    root / 'setup/source.py' if plan['arm'].startswith('oracle_') else None,
                )
                if (
                    plan['arm'] == 'judge_test'
                    and manifest['files']['test_source.py'] != load('gold/source-manifest.json')['sha256']
                ):
                    raise ValueError('public test source differs from executed reference')
        elif runner == 'cursor':
            if require_probes:
                raise ValueError('Use scripts/qualify_cursor.py for Cursor boundary probes')
            from gui_agent_bench.cursor_audit import audit_cursor_authoring

            report, denied, observed_images = audit_cursor_authoring(root, plan)
            manifest = load('workspace-manifest.json')
            if manifest['arm'] != plan['arm'] or manifest['platform'] != plan.get('platform'):
                raise ValueError('Cursor workspace differs from plan')
            if plan['arm'] != 'judge_visual':
                roles = load('cursor-networks.json')
                audit_broker(
                    load('broker-container.json'),
                    roles['gui']['Name'],
                    roles['capture']['Name'],
                    root / 'setup/source.py' if plan['arm'].startswith('oracle_') else None,
                )
                if (
                    plan['arm'] == 'judge_test'
                    and manifest['files']['test_source.py'] != load('gold/source-manifest.json')['sha256']
                ):
                    raise ValueError('public test source differs from executed reference')
        elif runner == 'claude':
            if require_probes:
                raise ValueError('Use scripts/qualify_claude.py for Claude Code boundary probes')
            from gui_agent_bench.claude_audit import audit_claude_authoring

            report, denied, observed_images = audit_claude_authoring(root, plan)
            manifest = load('workspace-manifest.json')
            if manifest['arm'] != plan['arm'] or manifest['platform'] != plan.get('platform'):
                raise ValueError('Claude Code workspace differs from plan')
            if plan['arm'] != 'judge_visual':
                roles = load('claude-networks.json')
                audit_broker(
                    load('broker-container.json'),
                    roles['gui']['Name'],
                    roles['capture']['Name'],
                    root / 'setup/source.py' if plan['arm'].startswith('oracle_') else None,
                )
                if (
                    plan['arm'] == 'judge_test'
                    and manifest['files']['test_source.py'] != load('gold/source-manifest.json')['sha256']
                ):
                    raise ValueError('public test source differs from executed reference')
        elif runner == 'opencode':
            manifest, config = (load('workspace-manifest.json'), load('config/opencode.json'))
            effective = load('effective-config.json')
            if effective['permission'] != config['permission'] or effective.get('plugin'):
                raise ValueError('effective config mismatch')
            report = audit_agent(
                load('agent-container.json'), root / 'workspace', manifest, config, load('agent-network.json')
            )
            if (root / 'fixture-control.json').exists():
                if plan.get('model') != 'fixture/scripted':
                    raise ValueError('Private fixture controls supplied to a real model')
                report['fixture_provider'] = audit_fixture_provider(
                    load('fixture-provider-container.json'), root, load('agent-network.json')['Name']
                )
            if manifest.get('platform', plan.get('platform', 'web')) != plan.get('platform', 'web') or (
                plan.get('platform') == 'tv' and manifest.get('platform') != 'tv'
            ):
                raise ValueError('workspace platform differs from plan')
            if manifest['arm'] != plan['arm']:
                raise ValueError('workspace arm differs from plan')
            if plan.get('model_variant') is not None:
                # The selected OpenCode variant must reach inference on every agent turn.
                records = [json.loads(line) for line in regular_file(root / 'logs/provider.ndjson', root).splitlines()]
                turns = [item for item in records if item.get('capabilities_verified')]
                applied = [item for item in records if item.get('variant_verified')]
                command = load('agent-container.json').get('Args') or []
                if (
                    not applied
                    or len(applied) != len(turns)
                    or any(item.get('reasoning_effort') != plan['model_variant'] for item in applied)
                    or any(item.get('capability_error') for item in records)
                    or command.count('--variant') != 1
                    or command[command.index('--variant') + 1] != plan['model_variant']
                ):
                    raise ValueError('selected OpenCode variant was not applied to every agent turn')
                report['model_variant'] = plan['model_variant']
            if plan['arm'] != 'judge_visual':
                agent_network = load('agent-network.json')['Name']
                audit_broker(
                    load('broker-container.json'),
                    agent_network,
                    agent_network.removesuffix('-inference') + '-capture',
                    root / 'setup/source.py' if plan['arm'].startswith('oracle_') else None,
                )
                if (
                    plan['arm'] == 'judge_test'
                    and manifest['files']['test_source.py'] != load('gold/source-manifest.json')['sha256']
                ):
                    raise ValueError('public test source differs from executed reference')
                provider_records = [
                    json.loads(line) for line in regular_file(root / 'logs/provider.ndjson', root).splitlines()
                ]
                expected_tools = ['gui_dump_ui', 'gui_observe', 'gui_open_url', 'gui_reset', 'gui_step']
                if plan['arm'].endswith('_visual'):
                    expected_tools.remove('gui_dump_ui')
                if plan.get('platform') == 'tv':
                    expected_tools = ['gui_observe', 'gui_reset', 'gui_step']
                verified = [item for item in provider_records if item.get('capabilities_verified')]
                if (
                    not verified
                    or any((item.get('gui_tools') != expected_tools for item in verified))
                    or any((item.get('capability_error') for item in provider_records))
                ):
                    raise ValueError('live judge capabilities were not delivered to inference')
            denied, observed_images = (set(), set())
            for line in regular_file(root / 'logs/agent/trajectory.ndjson', root, 16000000).splitlines():
                event = json.loads(line)
                if event.get('type') != 'tool_use':
                    continue
                part = event['part']
                state = part['state']
                path = state.get('input', {}).get('filePath')
                if path in forbidden or part['tool'] == 'bash':
                    if state['status'] != 'error':
                        raise ValueError('forbidden tool call succeeded')
                    denied.add(path if path in forbidden else 'bash')
                if path and path.startswith('/workspace/evidence/screenshots/') and (state['status'] == 'completed'):
                    observed_images.add(path)
            if require_probes and denied != forbidden | {'bash'}:
                raise ValueError('all explicit isolation probes must be denied')
            if plan['arm'] != 'judge_visual' and require_probes:
                records = [json.loads(line) for line in regular_file(root / 'logs/browser.ndjson', root).splitlines()]
                calls = [record for record in records if 'tool' in record]
                if plan.get('platform') == 'tv':
                    probes = [c for c in calls if c['tool'] == 'step' and c['denied']]
                    if not any((c['arguments'].get('action') == 'evaluate' for c in probes)) or not any(
                        ('state' in c['arguments'] for c in probes)
                    ):
                        raise ValueError('TV code and state-selection probes were not both denied')
                    permitted = ['observe', 'reset', 'step']
                else:
                    if not any((c['tool'] == 'open_url' and c['denied'] for c in calls)) or not any(
                        (c['tool'] == 'step' and c['denied'] for c in calls)
                    ):
                        raise ValueError('browser URL/code probes were not both denied')
                    permitted = ['observe', 'reset', 'open_url', 'step'] + (
                        [] if plan['arm'].endswith('_visual') else ['dump_ui']
                    )
                for name in permitted:
                    if not any(
                        (c['tool'] == name and (not c['denied']) and (not c.get('operation_failed')) for c in calls)
                    ):
                        raise ValueError('allowed browser capability not demonstrated')
        else:
            raise ValueError('Unrecognized explicit runner')
        report.update(audit_application(plan['task'], root, plan.get('platform')))
        if plan['arm'] != 'judge_visual':
            from gui_agent_bench.authoring_recovery import audit_recovery_events

            recovery_records = [
                json.loads(line) for line in regular_file(root / 'logs/browser.ndjson', root).splitlines()
            ]
            recovered = audit_recovery_events(recovery_records, plan.get('platform', 'web'))
            if runner in {'codex', 'cursor', 'claude'} and recovered != report.get('authoring_recoveries', []):
                raise ValueError('Account runner recovery differs from trusted broker reset ledger')
            report['authoring_recoveries'] = recovered
        submission = load('submission.json')
        filename = artifact_name(plan['arm'])
        if submission.get('present', True):
            sealed = regular_file(root / 'sealed' / filename, root, 65536)
            if digest(sealed) != submission['sha256']:
                raise ValueError('sealed artifact changed')
        elif (root / 'sealed' / filename).exists() or load('logs/verifier/metrics.json')['reward'] != 0:
            raise ValueError('missing submission must remain a zero')
        if generated(plan['arm']):
            from gui_agent_bench.verifier.oracle import audit_execution, audit_oracle_broker, classify, pair_result
            from gui_agent_bench.budgets import planned_variants

            audit_oracle_broker(load('broker-container.json'), plan['arm'], 'author')
            pair = root / 'verification'
            if (
                not (pair / 'plan.json').exists()
                or load('logs/verifier/metrics.json')['status'] == 'invalid_submission'
            ):
                if load('logs/verifier/metrics.json')['reward'] != 0:
                    raise ValueError('unexecuted oracle received credit')
                reports.append(
                    {
                        **report,
                        'trial_id': trial['id'],
                        'denied_probes': len(denied),
                        'execution_boundary_verified': False,
                    }
                )
                continue
            pair_plan = json.loads(regular_file(pair / 'plan.json', pair))
            from gui_agent_bench.visual import reference_digest, read_references, audit_images

            reference_dir = pair / 'sealed/references'
            reference_sha = reference_digest(reference_dir)
            if reference_sha != submission.get('references_sha256') or reference_sha != pair_plan.get(
                'references_sha256'
            ):
                raise ValueError('different references used for verification')
            if reference_digest(root / 'sealed/references') != reference_sha:
                raise ValueError('authoring references changed')
            manifest, _ = read_references(reference_dir)
            capture_records = [
                json.loads(line) for line in regular_file(root / 'logs/browser.ndjson', root).splitlines()
            ]
            captured = [r['reference'] for r in capture_records if 'reference' in r]
            if (
                len(captured) != len(manifest['references'])
                or {r['name']: {'file': r['file'], 'sha256': r['sha256']} for r in captured} != manifest['references']
            ):
                raise ValueError('reference images lack author observation provenance')
            paired_artifact = pair / 'sealed' / filename
            if (
                digest(regular_file(paired_artifact, pair, 65536)) != submission['sha256']
                or pair_plan['sha256'] != submission['sha256']
            ):
                raise ValueError('different oracle used for verification')
            if [e['variant'] for e in pair_plan['executions']] != planned_variants():
                raise ValueError('paired executions missing or reordered')
            results = []
            for entry in pair_plan['executions']:
                folder = pair / 'executions' / entry['id']
                read = lambda name: json.loads(regular_file(folder / name, folder))
                audit_application(plan['task'], folder, plan.get('platform'))
                audit_execution(read('executor-container.json'), read('executor-network.json'), paired_artifact)
                net = read('executor-network.json')['Name']
                full_test = plan['arm'].startswith('test_')
                audit_broker(
                    read('broker-container.json'),
                    net,
                    net.removesuffix('-inference') + '-capture',
                    None if full_test else folder / 'setup/source.py',
                    reference_dir,
                )
                audit_oracle_broker(read('broker-container.json'), plan['arm'], 'execute')
                if (
                    not full_test
                    and digest(regular_file(folder / 'setup/source.py', folder))
                    != load('gold/source-manifest.json')['sha256']
                ):
                    raise ValueError('verification setup differs from reference')
                records = [json.loads(line) for line in regular_file(folder / 'browser.log', folder).splitlines()]
                audit_images(folder / 'image-assertions', records, manifest)
                saved = read('result.json')
                state, termination = (read('executor-state.json'), read('termination.json'))
                if state['ExitCode'] != saved['exit_code'] or state['Running']:
                    raise ValueError('executor exit state differs')
                recovered = classify(
                    records,
                    state['ExitCode'],
                    termination['failure'],
                    full_test=full_test,
                    termination_causes=termination.get('causes'),
                )
                if 'diagnostics' in saved and saved['diagnostics'] != recovered['diagnostics']:
                    raise ValueError('execution diagnostics differ from trusted ledger')
                if (
                    recovered['outcome'] != saved['outcome']
                    or saved['submission_sha256'] != submission['sha256']
                    or saved.get('references_sha256') != reference_sha
                ):
                    raise ValueError('recorded execution differs from trusted ledger')
                results.append(recovered)
            if pair_result(results, planned_variants())['reward'] != load('logs/verifier/metrics.json')['reward']:
                raise ValueError('pair reward differs from ledger')
            report['execution_boundary_verified'] = True
        reports.append(
            {
                **report,
                'trial_id': trial['id'],
                'denied_probes': len(denied),
                'images_agent_chose_to_read': len(observed_images),
            }
        )
    return {
        'status': 'pass',
        'scope': f"Recorded {plan['arm']} boundary audit",
        'runtime_verified': True,
        'other_arms_verified': False,
        'trials': reports,
    }
