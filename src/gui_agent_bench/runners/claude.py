"""Claude Code CLI lifecycle: credential-free client, credential-injecting relay, guarded MCP bridge."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from gui_agent_bench.docker import docker, inspect, isolation, mount, client_environment
from gui_agent_bench.failures import Failure, issue, diagnostics
from gui_agent_bench.io import dump, regular_file
from .claude_auth import credentials, billing_mode
from .claude_config import IMAGES, VERSION, CONTRACT, budget, render, validate_lock, qualification_path
from .registry import fingerprint
from .cursor import export_file
from .cursor_logs import collect_gateway_logs, provider_records

LOG_CONTRACT = 'claude-provider-streams-v1'


def image_ids():
    return {role: json.loads(docker('image', 'inspect', name))[0]['Id'] for role, name in IMAGES.items()}


def require_qualification(root, spec, arm, platform, profile='generic'):
    certificate = json.loads(regular_file(qualification_path(root, spec), root))
    if (
        certificate.get('schema') != 'claude-qualification-v1'
        or certificate.get('status') != 'passed'
        or certificate.get('agent_spec') != spec.record()
        or certificate.get('resolved_model_id') != spec.model
        or certificate.get('runtime_lock_sha256') != fingerprint(validate_lock(root))
        or certificate.get('images') != image_ids()
        or [spec.model, arm, platform, profile] not in certificate.get('qualified_profiles', [])
    ):
        raise ValueError(
            'Claude Code selected model/arm/platform lacks current boundary qualification; run scripts/qualify_claude.py'
        )
    from gui_agent_bench.io import digest

    if not certificate.get('evidence') or any(
        digest(regular_file(root / name, root, 64_000_000)) != sha for name, sha in certificate['evidence'].items()
    ):
        raise ValueError('Claude Code boundary evidence is missing or changed')
    return certificate


def gateway_environment(spec, policy, limits, model_identity=''):
    return {
        'GAB_CLAUDE_AUTH_KIND': policy['auth_kind'],
        'GAB_CLAUDE_MODEL': spec.model,
        'GAB_CLAUDE_EFFORT': spec.reasoning_effort,
        'GAB_CLAUDE_TOOLS': ','.join(policy['tool_names']),
        'GAB_CLAUDE_REQUEST_LIMIT': str(limits['model_requests']),
        'GAB_CLAUDE_MODEL_IDENTITY': model_identity,
    }


def provider_record_success(row):
    return row.get('event') == 'request' and row.get('outcome') == 'completed' and row.get('status') == 200


def provider_failure_cause(row):
    """Map one relay record to a stable cause. Every non-success stays fatal."""
    reason = row.get('rejection_reason')
    if reason == 'request_budget':
        return 'budget_exhausted'
    if reason:
        return 'infrastructure_error'
    outcome, status, kind = row.get('outcome'), row.get('status'), row.get('error_type')
    if outcome == 'response_bytes':
        return 'evidence_overflow'
    if outcome in {'model_changed', 'model_identity'}:
        return 'infrastructure_error'
    if status == 429 or kind == 'rate_limit_error':
        return 'provider_rate_limit'
    if status == 529 or kind == 'overloaded_error':
        return 'provider_capacity'
    if status in {408, 504} or kind == 'timeout_error':
        return 'provider_timeout'
    if outcome in {'upstream_status', 'stream_error'}:
        return 'provider_error'
    return 'provider_transport_error'


def validate_provider(rows):
    requests = [row for row in rows if row.get('event') == 'request']
    if not requests or not all(provider_record_success(row) for row in requests):
        raise ValueError('Claude gateway failed or denied a request')
    if [row.get('sequence') for row in requests] != list(range(1, len(requests) + 1)):
        raise ValueError('Claude gateway request sequence differs')
    if len({row.get('resolved_model') for row in requests}) != 1:
        raise ValueError('Claude gateway observed more than one model')
    return requests


def identity_probe(root, spec, *, auth=None):
    """Resolve the selected model's catalog identity through the production gateway image.

    This is a qualification control: it sends one GET /v1/models request and
    starts no inference.
    """
    kind, value = auth or credentials()
    name = 'gab-claude-identity-' + os.urandom(6).hex()
    env = dict(client_environment(), GAB_CLAUDE_CREDENTIAL=value)
    settings = {
        'GAB_CLAUDE_AUTH_KIND': kind,
        'GAB_CLAUDE_MODEL': spec.model,
        'GAB_CLAUDE_EFFORT': spec.reasoning_effort,
        'GAB_CLAUDE_TOOLS': '',
        'GAB_CLAUDE_REQUEST_LIMIT': '0',
        'GAB_CLAUDE_IDENTITY_PROBE': '1',
    }
    try:
        docker(
            'create',
            '--name',
            name,
            '--user',
            f'{os.getuid()}:{os.getgid()}',
            *isolation(memory='256m'),
            '--env',
            'GAB_CLAUDE_CREDENTIAL',
            *[a for k, v in settings.items() for a in ('--env', k + '=' + v)],
            IMAGES['gateway'],
            env=env,
        )
        docker('start', '--attach', name, timeout=90, check=False)
        rows = [json.loads(line) for line in docker('logs', name, check=False).splitlines() if line.strip()]
    finally:
        docker('rm', '-f', name, check=False)
    if len(rows) != 1 or rows[0].get('event') != 'model_identity' or 'sha256' not in rows[0]:
        raise ValueError('Claude model identity is unavailable for this credential')
    return rows[0]


def launch(root, spec, context, credential_source, containers, networks, *, qualification=False, auth=None):
    """Run one authoring session. ``credential_source`` is unused: credentials come from the environment."""
    lock = validate_lock(root)
    certificate = None
    if not qualification:
        certificate = require_qualification(root, spec, context.arm, context.platform, context.environment_profile)
    kind, secret = auth or credentials()
    policy = render(context.config_directory, spec, context, kind)
    model_identity = (certificate or {}).get('resolved_model_id') or ''
    directory = context.public_workspace.parent
    limits = budget(context.arm, context.timeout_seconds)
    dump(
        directory / 'agent-plan.json',
        dict(
            **spec.record(),
            runner_version=VERSION,
            budgets=limits,
            billing_mode=billing_mode(kind),
            automatic_trial_retries=False,
            automatic_fallback=False,
            client_request_retries=0,
            provider_log_contract=LOG_CONTRACT,
            protocol_contract=CONTRACT,
        ),
    )
    dump(directory / 'runtime-manifest.json', dict(images=image_ids(), runtime_lock_sha256=fingerprint(lock)))
    prefix = 'gab-' + context.trial_id + '-claude'
    names = {r: prefix + '-' + r for r in IMAGES}
    inference = prefix + '-inference'
    bridge_audit = context.log_directory.parent / 'bridge'
    bridge_audit.mkdir(parents=True, exist_ok=True)
    process = None
    created = []
    problems = []
    active_error = None
    summary = dict(
        runner='claude', completed=False, usage=None, provider_cost_usd=None, billing_mode=billing_mode(kind)
    )
    try:
        with tempfile.TemporaryDirectory(prefix='gab-claude-ipc-') as ipc:

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
            settings = gateway_environment(spec, policy, limits, model_identity)
            gateway = create(
                'gateway',
                '--network',
                inference,
                '--network-alias',
                'provider',
                '--env',
                'GAB_CLAUDE_CREDENTIAL',
                *[a for k, v in settings.items() for a in ('--env', k + '=' + v)],
                IMAGES['gateway'],
                env=dict(client_environment(), GAB_CLAUDE_CREDENTIAL=secret),
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
            # The credential is checked in memory, then omitted entirely from
            # public inspect evidence. No key or token is serialized.
            gateway_env = details['gateway']['Config']['Env']
            if sum(e.startswith('GAB_CLAUDE_CREDENTIAL=') for e in gateway_env) != 1:
                raise Failure('policy_violation')
            details['gateway']['Config']['Env'] = [e for e in gateway_env if not e.startswith('GAB_CLAUDE_CREDENTIAL=')]
            details['gateway']['credential_environment_omitted'] = True
            nets = {
                r: json.loads(docker('network', 'inspect', n))[0]
                for r, n in {
                    'inference': inference,
                    'gui': context.gui_network,
                    'capture': context.gui_network.removesuffix('-inference') + '-capture',
                }.items()
            }
            from gui_agent_bench.claude_audit import audit_isolation

            dump(directory / 'claude-containers.json', details)
            dump(directory / 'claude-networks.json', nets)
            dump(directory / 'isolation.json', audit_isolation(details, nets, context))
            context.log_directory.mkdir(parents=True, exist_ok=True)
            process = subprocess.Popen(
                ['docker', 'start', '--attach', agent],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                env=client_environment(),
            )
            from .claude_protocol import capture

            summary = {**capture(process, context.log_directory, limits, policy), 'billing_mode': billing_mode(kind)}
            deadline = time.monotonic() + 10
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
            export_file(agent, '/run/mcp.ndjson', context.log_directory / 'mcp.ndjson')
            export_file(agent, '/run/guard.ndjson', context.log_directory / 'guard.ndjson')
            dump(context.log_directory / 'child.json', child)
            from gui_agent_bench.claude_audit import reconcile

            reconcile(
                directory,
                policy,
                context.platform,
                broker_log=(lambda: docker('logs', context.broker_container)) if context.broker_container else None,
            )
            return summary
    except BaseException as exc:
        active_error = exc
        problems.append(issue(exc, phase='authoring', operation='claude_lifecycle', impact='zero_credit'))
        raise
    finally:
        if names['agent'] in created:
            for source in ('mcp.ndjson', 'guard.ndjson', 'child.json'):
                destination = context.log_directory / source
                if not destination.exists():
                    try:
                        export_file(names['agent'], '/run/' + source, destination, optional=True)
                    except Exception as exc:
                        problems.append(
                            issue(exc, phase='controller', operation='claude_evidence_export', impact='zero_credit')
                        )
        logs = context.log_directory.parent
        if names['gateway'] in created:
            try:
                collect_gateway_logs(
                    names['gateway'],
                    logs / 'claude-provider.ndjson',
                    logs / 'claude-provider-stderr.log',
                    logs / 'claude-provider-streams.json',
                    contract=LOG_CONTRACT,
                )
            except Exception as exc:
                problems.append(
                    issue(exc, phase='inference', operation='claude_provider_collection', impact='zero_credit')
                )
        if names['bridge'] in created:
            (logs / 'claude-bridge-stderr.log').write_text(
                docker('logs', names['bridge'], check=False, include_stderr=True) + '\n'
            )
        provider_path = logs / 'claude-provider.ndjson'
        if provider_path.exists() and provider_path.stat().st_size:
            try:
                stderr_path = logs / 'claude-provider-stderr.log'
                if stderr_path.exists() and stderr_path.stat().st_size:
                    raise ValueError('Unexpected gateway stderr')
                for row in provider_records(provider_path):
                    if row.get('event') != 'request' or not provider_record_success(row):
                        problems.append(
                            issue(
                                Failure(provider_failure_cause(row)),
                                phase='inference',
                                operation='claude_provider',
                                impact='zero_credit',
                            )
                        )
            except (ValueError, TypeError):
                problems.append(
                    issue(
                        Failure('incomplete_trajectory'),
                        phase='inference',
                        operation='claude_provider_evidence',
                        impact='zero_credit',
                    )
                )
        elif names['gateway'] in created:
            problems.append(
                issue(
                    Failure('provider_transport_error'),
                    phase='inference',
                    operation='claude_provider',
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
        if sum(p.stat().st_size for p in logs.rglob('*') if p.is_file()) > limits['evidence_bytes']:
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
