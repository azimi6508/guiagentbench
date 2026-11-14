"""Cursor CLI lifecycle using a credential-free agent and guarded MCP bridge."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from gui_agent_bench.docker import docker, inspect, isolation, mount, client_environment
from gui_agent_bench.failures import Failure, issue, diagnostics
from gui_agent_bench.io import dump, regular_file
from .cursor_auth import access_token
from .cursor_config import IMAGES, VERSION, budget, render, validate_lock, qualification_path
from .registry import fingerprint
from .cursor_logs import CONTRACT as LOG_CONTRACT, collect_gateway_logs, provider_records


def image_ids():
    return {role: json.loads(docker('image', 'inspect', name))[0]['Id'] for role, name in IMAGES.items()}


def export_file(agent, source, destination, *, optional=False):
    # Docker cp cannot export tmpfs files on some engines. The fixed trusted
    # helper bounds bytes inside the container; no model-supplied command runs.
    script = (
        'import os,stat,sys; p=sys.argv[1]; f=os.open(p,os.O_RDONLY|os.O_NOFOLLOW); '
        's=os.fstat(f); assert stat.S_ISREG(s.st_mode) and s.st_size<=64000000; '
        'b=os.fdopen(f,"rb").read(64000001); assert len(b)<=64000000; sys.stdout.buffer.write(b)'
    )
    result = subprocess.run(
        ['docker', 'exec', agent, 'python', '-c', script, source],
        capture_output=True,
        timeout=15,
        env=client_environment(),
    )
    if result.returncode:
        if optional:
            return False
        raise Failure('incomplete_trajectory')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(result.stdout)
    return True


def require_qualification(root, spec, arm, platform, profile='generic'):
    certificate = json.loads(regular_file(qualification_path(root, spec), root))
    if (
        certificate.get('schema') != 'cursor-qualification-v1'
        or certificate.get('status') != 'passed'
        or certificate.get('agent_spec') != spec.record()
        or not isinstance(certificate.get('model_identity_sha256'), str)
        or len(certificate['model_identity_sha256']) != 64
        or certificate.get('runtime_lock_sha256') != fingerprint(validate_lock(root))
        or certificate.get('images') != image_ids()
        or [spec.model, arm, platform, profile] not in certificate.get('qualified_profiles', [])
    ):
        raise ValueError(
            'Cursor selected model/arm/platform lacks current boundary qualification; run scripts/qualify_cursor.py'
        )
    from gui_agent_bench.io import digest

    if not certificate.get('evidence') or any(
        digest(regular_file(root / name, root, 64_000_000)) != sha for name, sha in certificate['evidence'].items()
    ):
        raise ValueError('Cursor boundary evidence is missing or changed')


def launch(
    root,
    spec,
    context,
    credential_source,
    containers,
    networks,
    *,
    qualification=False,
    token=None,
    startup_only=False,
    identity_probe=False,
):
    lock = validate_lock(root)
    if not qualification:
        require_qualification(root, spec, context.arm, context.platform, context.environment_profile)
        if startup_only or identity_probe:
            raise ValueError('Startup-only mode is a qualification control')
    token = token or access_token(credential_source, root=root)
    policy = render(context.config_directory, spec, context)
    model_identity = ''
    if not qualification:
        certificate = json.loads(regular_file(qualification_path(root, spec), root))
        model_identity = certificate['model_identity_sha256']
    if startup_only:
        policy['startup_only'] = True
        dump(context.config_directory / 'agent.json', policy)
    directory = context.public_workspace.parent
    limits = budget(context.arm, context.timeout_seconds)
    dump(
        directory / 'agent-plan.json',
        dict(
            **spec.record(),
            runner_version=VERSION,
            budgets=limits,
            billing_mode='cursor_account',
            automatic_trial_retries=False,
            automatic_fallback=False,
            provider_log_contract=LOG_CONTRACT,
        ),
    )
    dump(directory / 'runtime-manifest.json', dict(images=image_ids(), runtime_lock_sha256=fingerprint(lock)))
    prefix = 'gab-' + context.trial_id + '-cursor'
    names = {r: prefix + '-' + r for r in IMAGES}
    inference = prefix + '-inference'
    bridge_audit = context.log_directory.parent / 'bridge'
    bridge_audit.mkdir(parents=True, exist_ok=True)
    process = None
    created = []
    problems = []
    active_error = None
    summary = dict(runner='cursor', completed=False, usage=None, provider_cost_usd=None, billing_mode='cursor_account')
    try:
        with tempfile.TemporaryDirectory(prefix='gab-cursor-ipc-') as ipc:

            def create(role, *args, env=None):
                name = names[role]
                containers.append(name)
                created.append(name)
                docker(
                    'create',
                    '--name',
                    name,
                    '--label',
                    f'gui-agent-bench.trial={context.trial_id}',
                    '--user',
                    f'{os.getuid()}:{os.getgid()}',
                    *isolation(),
                    *args,
                    env=env or client_environment(),
                )
                return name

            networks.append(inference)
            docker('network', 'create', '--internal', '--label', f'gui-agent-bench.trial={context.trial_id}', inference)
            env = dict(client_environment(), GAB_CURSOR_ACCESS_TOKEN=token)
            gateway = create(
                'gateway',
                '--network',
                inference,
                '--network-alias',
                'provider',
                '--env',
                'GAB_CURSOR_ACCESS_TOKEN',
                '--env',
                'GAB_CURSOR_PAYLOAD_LIMIT=' + str(limits['relay_payload_requests']),
                '--env',
                'GAB_CURSOR_HEARTBEAT_LIMIT=' + str(limits['relay_heartbeat_requests']),
                '--env',
                'GAB_CURSOR_METADATA_LIMIT=' + str(limits['relay_metadata_requests']),
                '--env',
                'GAB_CURSOR_MODEL=' + spec.model,
                '--env',
                'GAB_CURSOR_MODEL_IDENTITY=' + model_identity,
                *(['--env', 'GAB_CURSOR_IDENTITY_PROBE=1'] if identity_probe else []),
                IMAGES['gateway'],
                env=env,
            )
            docker('network', 'connect', 'bridge', gateway)
            docker('start', gateway)
            bridge = create(
                'bridge',
                '--network',
                'none' if context.arm == 'judge_visual' else context.gui_network,
                *mount(context.public_workspace, '/workspace'),
                *mount(context.output_directory, '/workspace/output', writable=True),
                *mount(context.config_directory, '/policy'),
                *mount(bridge_audit, '/audit', writable=True),
                *mount(Path(ipc), '/ipc', writable=True),
                IMAGES['bridge'],
            )
            docker('start', bridge)
            deadline = time.monotonic() + 30
            while not (Path(ipc) / 'bench.sock').exists():
                if time.monotonic() >= deadline or not inspect(bridge)['State']['Running']:
                    raise Failure('capability_unavailable')
                time.sleep(0.05)
            agent = create(
                'agent',
                '--network',
                inference,
                '--security-opt',
                'apparmor=docker-default',
                '--tmpfs',
                f'/run:rw,nosuid,nodev,size=512m,mode=0700,uid={os.getuid()},gid={os.getgid()}',
                *mount(context.config_directory, '/policy'),
                *mount(Path(ipc), '/ipc'),
                IMAGES['agent'],
            )
            details = {r: inspect(n) for r, n in names.items()}
            # Gateway authentication is checked in memory, then omitted entirely
            # from public inspect evidence. No API key or token is serialized.
            gateway_env = details['gateway']['Config']['Env']
            if sum(e.startswith('GAB_CURSOR_ACCESS_TOKEN=') for e in gateway_env) != 1:
                raise Failure('policy_violation')
            details['gateway']['Config']['Env'] = [
                e for e in gateway_env if not e.startswith('GAB_CURSOR_ACCESS_TOKEN=')
            ]
            details['gateway']['credential_environment_omitted'] = True
            nets = {
                r: json.loads(docker('network', 'inspect', n))[0]
                for r, n in {
                    'inference': inference,
                    'gui': context.gui_network,
                    'capture': context.gui_network.removesuffix('-inference') + '-capture',
                }.items()
            }
            from gui_agent_bench.cursor_audit import audit_isolation

            dump(directory / 'cursor-containers.json', details)
            dump(directory / 'cursor-networks.json', nets)
            dump(directory / 'isolation.json', audit_isolation(details, nets, context))
            context.log_directory.mkdir(parents=True, exist_ok=True)
            process = subprocess.Popen(
                ['docker', 'start', '--attach', agent],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                env=client_environment(),
            )
            from .cursor_protocol import capture

            if not startup_only:
                summary = capture(process, context.log_directory, limits)
            deadline = time.monotonic() + (90 if startup_only else 10)
            while time.monotonic() < deadline:
                raw = docker('exec', agent, 'cat', '/run/child.json', check=False)
                if raw:
                    child = json.loads(raw)
                    break
                time.sleep(0.1)
            else:
                raise Failure('incomplete_trajectory')
            if child != {'exit_code': 0}:
                raise Failure('incomplete_trajectory')
            if startup_only:
                # The child has exited; its short catalog output is bounded and
                # the supervisor only holds the tmpfs open for evidence export.
                import selectors

                selector = selectors.DefaultSelector()
                selector.register(process.stdout, selectors.EVENT_READ, 'cursor-catalog.txt')
                selector.register(process.stderr, selectors.EVENT_READ, 'cursor-stderr.log')
                try:
                    for key, _ in selector.select(0.2):
                        data = os.read(key.fileobj.fileno(), 1_048_577)
                        if len(data) > 1_048_576:
                            raise Failure('evidence_overflow')
                        (context.log_directory / key.data).write_bytes(data)
                finally:
                    selector.close()
                summary.update(completed=True, startup_only=True, observed_tool_items=0)
            export_file(agent, '/run/mcp.ndjson', context.log_directory / 'mcp.ndjson')
            export_file(agent, '/run/guard.ndjson', context.log_directory / 'guard.ndjson')
            dump(context.log_directory / 'child.json', child)
            from gui_agent_bench.cursor_audit import reconcile

            reconcile(
                directory,
                policy,
                context.platform,
                broker_log=(lambda: docker('logs', context.broker_container)) if context.broker_container else None,
            )
            return summary
    except BaseException as exc:
        active_error = exc
        problems.append(issue(exc, phase='authoring', operation='cursor_lifecycle', impact='zero_credit'))
        raise
    finally:
        # Export all available evidence before the tmpfs-bearing container stops.
        if names['agent'] in created:
            for source, target in [
                ('mcp.ndjson', 'mcp.ndjson'),
                ('guard.ndjson', 'guard.ndjson'),
                ('child.json', 'child.json'),
            ]:
                destination = context.log_directory / target
                if not destination.exists():
                    try:
                        export_file(names['agent'], '/run/' + source, destination, optional=True)
                    except Exception as exc:
                        problems.append(
                            issue(exc, phase='controller', operation='cursor_evidence_export', impact='zero_credit')
                        )
        for role in ('gateway', 'bridge'):
            if names[role] in created:
                if role == 'gateway':
                    try:
                        collect_gateway_logs(
                            names[role],
                            context.log_directory.parent / 'cursor-provider.ndjson',
                            context.log_directory.parent / 'cursor-provider-stderr.log',
                            context.log_directory.parent / 'cursor-provider-streams.json',
                        )
                    except Exception as exc:
                        problems.append(
                            issue(exc, phase='inference', operation='cursor_provider_collection', impact='zero_credit')
                        )
                else:
                    (context.log_directory.parent / 'cursor-bridge-stderr.log').write_text(
                        docker('logs', names[role], check=False, include_stderr=True) + '\n'
                    )
        provider_path = context.log_directory.parent / 'cursor-provider.ndjson'
        if provider_path.exists():
            try:
                stderr_path = context.log_directory.parent / 'cursor-provider-stderr.log'
                if stderr_path.exists() and stderr_path.stat().st_size:
                    raise ValueError('Unexpected gateway stderr')
                for row in provider_records(provider_path):
                    if not provider_record_success(row):
                        cause = provider_failure_cause(row)
                        problems.append(
                            issue(Failure(cause), phase='inference', operation='cursor_provider', impact='zero_credit')
                        )
            except (ValueError, TypeError):
                problems.append(
                    issue(
                        Failure('incomplete_trajectory'),
                        phase='inference',
                        operation='cursor_provider_evidence',
                        impact='zero_credit',
                    )
                )
        if names['agent'] in created:
            docker('stop', '--time', '2', names['agent'], check=False)
        if process:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        summary['diagnostics'] = diagnostics(problems)
        if (
            sum(p.stat().st_size for p in context.log_directory.parent.rglob('*') if p.is_file())
            > limits['evidence_bytes']
        ):
            problems.append(
                issue(
                    Failure('evidence_overflow'), phase='authoring', operation='combined_evidence', impact='zero_credit'
                )
            )
            summary['diagnostics'] = diagnostics(problems)
        summary['completed'] = bool(summary.get('completed')) and not problems
        dump(context.log_directory / 'summary.json', summary)
        if active_error is not None:
            active_error.diagnostic_issues = problems
        elif problems:
            failure = Failure('infrastructure_error')
            failure.diagnostic_issues = problems
            raise failure


def provider_record_success(row):
    """Only reviewed successful relay records; denials always remain fatal."""
    if row.get('outcome') == 'client_closed_before_request':
        return (
            row.get('event') == 'client_connection_closed_before_request'
            and row.get('path') is None
            and row.get('status') is None
            and row.get('stage') == 'request_line'
            and row.get('request_category') is None
            and row.get('exception_kind') == 'ConnectionResetError'
            and row.get('sent_bytes') == 0
            and row.get('received_bytes') == 0
            and not row.get('rejection_reason')
            and not row.get('dispatch_denial')
            and not row.get('provider_error')
            and not row.get('privacy_snapshot')
        )
    snapshot = row.get('privacy_snapshot')
    cached = row.get('outcome') == 'trial_privacy_cache'
    if snapshot is not None or cached:
        import re

        if (
            not isinstance(snapshot, dict)
            or set(snapshot) != {'event', 'age_ms', 'generation', 'request_sha256', 'response_sha256'}
            or row.get('path') != '/aiserver.v1.DashboardService/GetUserPrivacyMode'
            or row.get('request_category') != 'metadata'
            or type(snapshot.get('generation')) is not int
            or snapshot['generation'] < 1
            or type(snapshot.get('age_ms')) is not int
            or not 0 <= snapshot['age_ms'] < 60_000
            or any(
                not isinstance(snapshot.get(key), str) or re.fullmatch('[0-9a-f]{64}', snapshot[key]) is None
                for key in ('request_sha256', 'response_sha256')
            )
        ):
            return False
        if cached or snapshot['event'] == 'served':
            cancelled = row.get('outcome') == 'client_closed_after_metadata' and row.get('exception_kind') in {
                'BrokenPipeError',
                'ConnectionResetError',
            }
            if (
                snapshot['event'] != 'served'
                or row.get('sent_bytes') != 0
                or row.get('received_bytes') != 0
                or not (cancelled or cached and not row.get('exception_kind'))
            ):
                return False
        elif (
            snapshot['event'] != 'captured'
            or snapshot['age_ms'] != 0
            or row.get('outcome') not in {'completed', 'client_closed_after_metadata'}
        ):
            return False
    return (
        row.get('status') == 200
        and not row.get('rejection_reason')
        and not row.get('dispatch_denial')
        and not row.get('provider_error')
        and row.get('outcome')
        in {'completed', 'local_metadata', 'trial_catalog_cache', 'client_closed_after_metadata', 'trial_privacy_cache'}
    )


def provider_failure_cause(row):
    # A rejected local request is infrastructure evidence, not a provider outage
    # or a model-attributable budget failure. Operator reason codes stay in the
    # relay record; evaluated/public replies retain the stable cause contract.
    if row.get('rejection_reason') or str(row.get('stage', '')).startswith('request'):
        return 'infrastructure_error'
    if row.get('dispatch_denial') or row.get('stage') in {
        'frame_dispatch',
        'response_credentials',
        'stream_encoding',
        'frame_header',
    }:
        return 'infrastructure_error'
    return (
        'provider_rate_limit'
        if row.get('status') == 429
        else 'provider_error' if row.get('status') else 'provider_transport_error'
    )
