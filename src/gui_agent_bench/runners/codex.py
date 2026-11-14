"""Trusted Codex lifecycle. Task/private paths are intentionally absent here."""

import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from gui_agent_bench.budgets import codex_budget
from gui_agent_bench.codex_bridge import catalog
from gui_agent_bench.docker import docker, inspect, isolation, mount, client_environment
from gui_agent_bench.failures import Failure, diagnostics, issue
from gui_agent_bench.io import dump, digest, regular_file
from .codex_auth import AuthSession, source_path, LIMIT
from .codex_config import IMAGES, VERSION, render, validate_lock, qualification_path
from .codex_protocol import Driver
from .codex_startup import startup
from .registry import fingerprint
from .codex_security import options as security_options, policy as security_policy


def native_boundary(root=Path(__file__).resolve().parents[3]):
    # Exercise the actual named policy. A raw bwrap --ro-bind / / --proc probe
    # rejects Docker's masked proc paths even when Codex's supported no-proc
    # path can enforce this policy. No policy or filesystem override is used.
    setup = (
        'from pathlib import Path;import subprocess;'
        'Path("/run/codex/config.toml").symlink_to("/config/base.toml");'
        'r=subprocess.run(["/opt/codex/bin/codex","sandbox","-P","bench",'
        '"--include-managed-config","--cd","/session","--","/usr/bin/true"]);'
        'raise SystemExit(r.returncode)'
    )
    tmpfs = []
    for name, size in [('codex', '64m'), ('home', '16m')]:
        tmpfs += ['--tmpfs', f'/run/{name}:rw,nosuid,nodev,size={size},mode=0700,uid={os.getuid()},gid={os.getgid()}']
    result = subprocess.run(
        [
            'docker',
            'run',
            '--rm',
            '--network',
            'none',
            *isolation(),
            *security_options(root),
            *tmpfs,
            *mount(root / 'configs/codex', '/config'),
            '--user',
            f'{os.getuid()}:{os.getgid()}',
            '--entrypoint',
            '/usr/local/bin/python',
            IMAGES['agent'],
            '-c',
            setup,
        ],
        capture_output=True,
        timeout=30,
        env=client_environment(),
    )
    if result.returncode:
        raise ValueError(
            'Codex unavailable: the required Linux user-namespace sandbox fails with the pinned Codex container policy; check that its named AppArmor profile is loaded'
        )


def require_qualification(root, spec, arm, platform, profile='generic'):
    catalog(arm, platform, profile)
    path = qualification_path(root, spec)
    if not path.is_file():
        raise ValueError('Codex unavailable: actual-client and Docker boundary qualification has not passed')
    value = json.loads(path.read_text())
    lock = validate_lock(root)
    if (
        value.get('status') != 'passed'
        or value.get('runtime_lock_sha256') != fingerprint(lock)
        or value.get('images') != image_ids()
        or [spec.model, spec.reasoning_effort, arm, platform] not in value.get('qualified_profiles', [])
    ):
        raise ValueError('Codex unavailable: selected model/arm/platform lacks current runtime qualification')
    if profile != 'generic' and [spec.model, spec.reasoning_effort, arm, platform, profile] not in value.get(
        'qualified_environment_profiles', []
    ):
        raise ValueError('Codex unavailable: selected environment tool profile lacks current runtime qualification')


def image_ids():
    return {role: json.loads(docker('image', 'inspect', image))[0]['Id'] for role, image in IMAGES.items()}


def enforce_evidence_budget(log_directory, limit):
    total = sum(p.stat().st_size for p in Path(log_directory).rglob('*') if p.is_file())
    if total > limit:
        raise Failure('evidence_overflow')
    return total


def launch(root, spec, context, credential_source, containers, networks, *, infer=True, list_models=False):
    """Resources register before creation; protocol/auth finalize before removal.

    The enclosing trial owns the supplied container/network registry. Temporary
    auth and socket directories stay alive until these containers are removed.
    """
    lock = validate_lock(root)
    native_boundary(root)
    if infer:
        require_qualification(root, spec, context.arm, context.platform, context.environment_profile)
    directory = context.public_workspace.parent
    budget = codex_budget(context.arm, context.timeout_seconds)
    config = render(root, context.config_directory, spec, context.arm, context.platform, context.environment_profile)
    dump(
        directory / 'agent-plan.json',
        dict(
            **spec.record(),
            runner_version=VERSION,
            budgets=budget,
            automatic_trial_retries=False,
            automatic_fallback=False,
            billing_mode='chatgpt_subscription',
        ),
    )
    dump(
        directory / 'runtime-manifest.json',
        dict(images=image_ids(), runtime_lock_sha256=fingerprint(lock), container_policy=security_policy(root)),
    )
    dump(
        context.config_directory / 'bridge.json',
        dict(
            arm=context.arm,
            platform=context.platform,
            viewport=context.viewport,
            manifest=context.workspace_manifest,
            environment_profile=context.environment_profile,
        ),
    )
    tools = catalog(context.arm, context.platform, context.environment_profile)
    prefix = 'gab-' + context.trial_id
    names = {r: prefix + '-codex-' + r for r in ('agent', 'bridge', 'egress')}
    net = prefix + '-codex-inference'
    network_roles = dict(
        gui=context.gui_network, capture=context.gui_network.removesuffix('-inference') + '-capture', inference=net
    )
    bridge_audit = context.log_directory.parent / 'bridge'
    bridge_audit.mkdir(parents=True, exist_ok=True)
    driver = process = None
    created = []
    issues = []
    shutdown = 'failed'
    auth_persisted = False
    started = time.monotonic()

    def create(role, *args):
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
            *(security_options(root) if role == 'agent' else []),
            *args,
            env=client_environment(),
        )
        return name

    with (
        AuthSession(source_path(credential_source), excluded=[root, directory]) as auth,
        tempfile.TemporaryDirectory(prefix='gab-ipc-') as ipc,
    ):
        try:
            networks.append(net)
            docker('network', 'create', '--internal', '--label', f'gui-agent-bench.trial={context.trial_id}', net)
            proxy = create('egress', '--network', net, '--network-alias', 'egress', IMAGES['egress'])
            docker('network', 'connect', 'bridge', proxy)
            docker('start', proxy)
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
            tmpfs = []
            for path, size in [('/run/codex', '512m'), ('/run/home', '16m'), ('/run/control', '1m')]:
                tmpfs += [
                    '--tmpfs',
                    f'{path}:rw,nosuid,nodev,size={size},mode=0700,uid={os.getuid()},gid={os.getgid()}',
                ]
            agent = create(
                'agent',
                '--interactive',
                '--network',
                net,
                *tmpfs,
                '--env',
                'HTTPS_PROXY=http://egress:8080',
                '--env',
                'HTTP_PROXY=http://egress:8080',
                *mount(context.config_directory, '/config'),
                *mount(auth.staged, '/auth-input/auth.json'),
                *mount(Path(ipc), '/ipc'),
                IMAGES['agent'],
            )
            details = {r: inspect(names[r]) for r in names}
            nets = {r: json.loads(docker('network', 'inspect', n))[0] for r, n in network_roles.items()}
            from gui_agent_bench.codex_audit import audit_isolation

            attestation = audit_isolation(details, nets, context, auth.staged, Path(ipc))
            dump(directory / 'isolation.json', attestation)
            dump(directory / 'codex-containers.json', details)
            dump(directory / 'codex-networks.json', nets)
            process = subprocess.Popen(
                ['docker', 'start', '--attach', '--interactive', agent],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                env=client_environment(),
            )
            auth_data = json.loads(auth.staged.read_bytes())
            secrets = list(auth_data['tokens'].values()) + [auth_data.get('OPENAI_API_KEY')]
            driver = Driver(process, context.log_directory, budget, secrets=secrets)
            result = startup(driver, spec, config, tools, list_models=list_models, expected_hooks=lock['hooks'])
            dump(context.log_directory / 'startup.json', result)
            dump(
                directory / 'effective-config.json',
                {'privacy_projection': True, 'config': config, 'sha256': fingerprint(config)},
            )
            if infer:
                instruction = regular_file(
                    context.public_workspace / 'instruction.md', context.public_workspace, 65_536
                )
                if digest(instruction) != context.workspace_manifest['files']['instruction.md']:
                    raise Failure('incomplete_trajectory')
                driver.turn(
                    spec.model,
                    spec.reasoning_effort,
                    context.timeout_seconds,
                    instruction=instruction.decode('utf-8', 'strict'),
                )
                from gui_agent_bench.codex_audit import reconcile

                reconcile(
                    context.log_directory,
                    bridge_audit,
                    tools,
                    context.platform,
                    broker_log=(lambda: docker('logs', context.broker_container)) if context.broker_container else None,
                )
            shutdown = 'completed' if infer else 'startup_only'
            return result
        except BaseException as exc:
            issues.append(issue(exc, phase='authoring', operation='codex_lifecycle', impact='zero_credit'))
            if driver:
                driver.interrupt()
            raise
        finally:
            # Never use docker() for auth export: its string/error/logging paths
            # are designed for public evidence, not credentials.
            if names['agent'] in created:
                try:
                    export = subprocess.Popen(
                        [
                            'docker',
                            'exec',
                            names['agent'],
                            '/usr/local/bin/python',
                            '/opt/bench/entrypoint.py',
                            'export-auth',
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        env=client_environment(),
                    )
                    import selectors

                    selection = selectors.DefaultSelector()
                    selection.register(export.stdout, selectors.EVENT_READ)
                    data = bytearray()
                    deadline = time.monotonic() + 5
                    try:
                        while time.monotonic() < deadline:
                            if not selection.select(0.1):
                                continue
                            block = os.read(export.stdout.fileno(), 65536)
                            if not block:
                                break
                            data.extend(block)
                            if len(data) > LIMIT:
                                raise ValueError()
                        else:
                            raise ValueError()
                        if export.wait(timeout=1) != 0:
                            raise ValueError()
                        auth.persist(bytes(data))
                        auth_persisted = True
                    finally:
                        selection.close()
                        if export.poll() is None:
                            export.kill()
                        export.wait(timeout=2)
                        data.clear()
                except Exception:
                    issues.append(
                        issue(
                            Failure('infrastructure_error'),
                            phase='controller',
                            operation='auth_refresh_persistence',
                            impact='zero_credit',
                        )
                    )
                docker(
                    'exec',
                    names['agent'],
                    '/usr/local/bin/python',
                    '/opt/bench/entrypoint.py',
                    'shutdown',
                    check=False,
                    timeout=10,
                )
            if process:
                if process.stdin:
                    process.stdin.close()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            if driver:
                if shutdown == 'completed':
                    try:
                        driver.drain()
                        from gui_agent_bench.codex_audit import reconcile

                        reconcile(
                            context.log_directory,
                            bridge_audit,
                            tools,
                            context.platform,
                            broker_log=(
                                (lambda: docker('logs', context.broker_container)) if context.broker_container else None
                            ),
                        )
                    except Exception as exc:
                        issues.append(issue(exc, phase='authoring', operation='drain_protocol', impact='zero_credit'))
                driver.close()
            if names['egress'] in created:
                (context.log_directory.parent / 'egress.ndjson').write_text(
                    docker('logs', names['egress'], check=False)
                )
            try:
                enforce_evidence_budget(context.log_directory.parent, budget['evidence_bytes'])
            except Failure as exc:
                issues.append(issue(exc, phase='authoring', operation='combined_evidence', impact='zero_credit'))
            for name in reversed(created):
                docker('rm', '-f', name, check=False)
            # trial's final registry cleanup is idempotent, and attests removal.
            summary = dict(
                runner='codex',
                runner_version=VERSION,
                tool_profile=spec.tool_profile,
                budget_profile=spec.budget_profile,
                completed=shutdown == 'completed' and not issues,
                shutdown_reason=shutdown,
                elapsed_seconds=time.monotonic() - started,
                observed_tool_items=driver.tool_items if driver else 0,
                auth_refresh_persisted=auth_persisted,
                diagnostics=diagnostics(issues),
                automatic_trial_retries=False,
                automatic_fallback=False,
                **(
                    driver.usage.record()
                    if driver
                    else {
                        'usage': None,
                        'usage_complete': False,
                        'provider_cost_usd': None,
                        'billing_mode': 'chatgpt_subscription',
                    }
                ),
            )
            dump(context.log_directory / 'summary.json', summary)
            if issues and shutdown in {'completed', 'startup_only'}:
                raise Failure('infrastructure_error')
