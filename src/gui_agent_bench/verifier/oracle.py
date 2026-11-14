"""Trusted paired-execution controller. Submitted Python runs only in the isolated executor."""

import ast
import json
from pathlib import Path
import subprocess
import time
import uuid
from gui_agent_bench.docker import docker, inspect, isolation, mount, WORKER_IMAGE, ORACLE_IMAGE, ORACLE_BROWSER_IMAGE
from gui_agent_bench.io import digest, dump, regular_file, same_source
from gui_agent_bench.task_runtime import runtime, app_isolation, browser_args
from gui_agent_bench.verifier.judge import write_result
from gui_agent_bench.arms import artifact_name
from gui_agent_bench.budgets import EXECUTIONS_PER_VERSION, execution_timeout, planned_variants
from gui_agent_bench.mobile_session import relay_args, start_app
from gui_agent_bench.applications import app_mounts
from gui_agent_bench.visual import reference_digest, seal_references, collect_files, VERSION, COMPARATOR
from gui_agent_bench.environment import VERSION as ENVIRONMENT_VERSION
from gui_agent_bench.failures import Failure, issue, diagnostics, record_issues, VERSION as FAILURE_VERSION


def seal(source, destination, function='check'):
    data = regular_file(source, source.parent, 65536)
    tree = ast.parse(data.decode('utf-8'))
    if not any((isinstance(node, ast.FunctionDef) and node.name == function for node in tree.body)):
        raise ValueError(f'{function}(page) is required')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return digest(data)


def _classify_outcome(records, exit_code, failure=None, full_test=False):
    if failure:
        return {'outcome': failure, 'assertions': []}
    if exit_code != 0:
        return {'outcome': 'ERROR', 'assertions': []}
    if any((record.get('denied') or record.get('operation_failed') for record in records)):
        return {'outcome': 'INVALID', 'assertions': []}
    assertions = [r for r in records if 'assertion' in r]
    preconditions = [a for a in assertions if a['assertion']['precondition']]
    behavior = [a for a in assertions if not a['assertion']['precondition']]
    if not preconditions or not behavior or (not assertions[0]['assertion']['precondition']):
        return {'outcome': 'INVALID', 'assertions': assertions}
    if any((a.get('matched') is not True for a in preconditions)):
        return {'outcome': 'SETUP_ERROR', 'assertions': assertions}
    if any((type(a.get('matched')) is not bool for a in behavior)):
        return {'outcome': 'INVALID', 'assertions': assertions}
    result = {'outcome': 'PASS' if all((a['matched'] for a in behavior)) else 'BEHAVIOR_FAIL', 'assertions': assertions}
    if full_test:
        actions = [r for r in records if 'action' in r]
        if not actions:
            return {'outcome': 'INVALID', 'assertions': assertions, 'actions': []}
        result['actions'] = actions
        result['trace'] = [
            {'action': r['action']} if 'action' in r else {'assertion': r['assertion']}
            for r in records
            if 'action' in r or 'assertion' in r
        ]
    return result


def classify(records, exit_code, failure=None, full_test=False, termination_causes=None):
    result = _classify_outcome(records, exit_code, failure, full_test)
    issues = record_issues(records, phase='execution', source='browser.log')
    for failed in termination_causes if termination_causes is not None else [failure] if failure else []:
        cause = {
            'TIMEOUT': 'execution_timeout',
            'OUTPUT_LIMIT': 'evidence_overflow',
            'RESOURCE_LIMIT': 'resource_limit',
            'INFRA_ERROR': 'infrastructure_error',
        }.get(failed, 'unknown_operation_error')
        issues.append(
            issue(
                Failure(cause),
                phase='execution',
                operation='process',
                impact='zero_credit',
                source={'file': 'termination.json'},
            )
        )
    if exit_code != 0:
        issues.append(
            issue(
                Failure('process_error'),
                phase='execution',
                operation='process',
                impact='zero_credit',
                source={'file': 'executor-state.json'},
            )
        )
    if result['outcome'] == 'INVALID' and (not any((i['impact'] == 'zero_credit' for i in issues))):
        issues.append(
            issue(
                Failure('missing_checks'),
                phase='execution',
                operation='validate_checks',
                impact='zero_credit',
                source={'file': 'browser.log'},
            )
        )
    result['diagnostics'] = diagnostics(issues)
    return result


def audit_oracle_broker(details, arm, mode):
    command = details['Config']['Cmd']
    if (
        command[:2] != ['-m', 'gui_agent_bench.oracle_broker']
        or command[command.index('--arm') + 1] != arm
        or command[command.index('--mode') + 1] != mode
    ):
        raise ValueError('oracle broker capability profile differs')


def pair_result(results, variants=None):
    """Grade repeated executions of one fixed artifact on both versions.

    Credit requires every correct-version execution to pass, every
    faulty-version execution to fail behaviorally, and every execution to run
    the same assertion definitions (and, for complete tests, the same action
    and assertion trace). An unusable repetition or a disagreement among
    repetitions of the same version earns no credit.
    """
    expected = planned_variants()
    if variants is None:
        recorded = [r.get('variant') for r in results]
        # Unlabelled results follow the planned interleaved order.
        variants = recorded if any(recorded) else (['correct', 'faulty'] * len(results))[: len(results)]
    variants = list(variants)
    valid = (
        len(results) == len(expected)
        and variants == expected
        and all((r['outcome'] in {'PASS', 'BEHAVIOR_FAIL'} for r in results))
    )
    signatures = [[r['assertion'] for r in result.get('assertions', [])] for result in results]
    traces = [result.get('trace') for result in results]
    comparable = valid and all((s == signatures[0] for s in signatures)) and all((t == traces[0] for t in traces))
    outcomes = {name: {r['outcome'] for r, v in zip(results, variants) if v == name} for name in ('correct', 'faulty')}
    stable = comparable and all((len(values) == 1 for values in outcomes.values()))
    reward = int(stable and outcomes['correct'] == {'PASS'} and outcomes['faulty'] == {'BEHAVIOR_FAIL'})
    issues = [
        {**item, 'execution_index': index}
        for index, result in enumerate(results)
        for item in result.get('diagnostics', {}).get('issues', [])
    ]
    if valid and (not comparable):
        issues.append(
            issue(Failure('incomparable_pair'), phase='grading', operation='compare_pair', impact='zero_credit')
        )
    elif comparable and (not stable):
        issues.append(
            issue(Failure('unstable_execution'), phase='grading', operation='compare_repetitions', impact='zero_credit')
        )
    return {
        'status': 'graded' if comparable else 'invalid_execution',
        'reward': reward,
        'same_assertions': bool(comparable),
        'stable': bool(stable),
        'executions': results,
        'diagnostics': diagnostics(issues),
    }


def audit_execution(details, network, artifact):
    host = details['HostConfig']
    if (
        not network['Internal']
        or set(details['NetworkSettings']['Networks']) != {network['Name']}
        or (not host['ReadonlyRootfs'])
        or host['Privileged']
        or (host.get('PidMode') == 'host')
        or (host.get('IpcMode') == 'host')
        or ('ALL' not in host['CapDrop'])
        or (not any((s.startswith('no-new-privileges') for s in host['SecurityOpt'])))
        or (not 0 < host['Memory'] <= 256 * 1024 * 1024)
        or (not 0 < host['PidsLimit'] <= 32)
        or (details['Config']['User'] != 'oracle')
    ):
        raise ValueError('oracle execution isolation differs')
    binds = [m for m in details['Mounts'] if m['Type'] == 'bind']
    destination = '/artifact/' + artifact.name
    if (
        len(binds) != 1
        or binds[0]['Destination'] != destination
        or binds[0]['RW']
        or not same_source(binds[0]['Source'], artifact)
        or any((m['Type'] not in {'tmpfs', 'bind'} for m in details['Mounts']))
    ):
        raise ValueError('execution mounts exceed sealed artifact')
    expected_env = {
        'PATH=/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        'LANG=C.UTF-8',
        'GPG_KEY=7169605F62C751356D054A26A821E680E5FA6305',
        'PYTHON_VERSION=3.12.8',
        'PYTHON_SHA256=c909157bb25ec114e5869124cc2a9c4a4d4c1e957ca4ff553f1edc692101154e',
        'PYTHONDONTWRITEBYTECODE=1',
        'PYTHONUNBUFFERED=1',
    }
    if set(details['Config']['Env']) != expected_env:
        raise ValueError('execution environment differs from pinned defaults')
    expected_command = ['--kind', 'test'] if artifact.name == 'test.py' else None
    if details['Config']['Cmd'] != expected_command:
        raise ValueError('execution entry point differs')
    return {'status': 'pass', 'network': network['Name'], 'mounts': [destination], 'image': details['Image']}


def execute(task, artifact, folder, variant, arm, artifact_hash, timeout=60, references=None, references_hash=None):
    from gui_agent_bench.audit import audit_broker

    folder.mkdir(parents=True)
    config = runtime(task)
    prefix = 'gab-oracle-' + uuid.uuid4().hex[:12]
    capture_net, client_net = (prefix + '-capture', prefix + '-inference')
    containers, networks = ([], [])
    mobile_session = None
    result = {
        'outcome': 'SETUP_ERROR',
        'assertions': [],
        'submission_sha256': artifact_hash,
        'references_sha256': references_hash,
    }
    full_test = arm.startswith('test_')
    source = None if full_test else folder / 'setup/source.py'
    phase, operation = ('setup', 'prepare_execution')
    if source is not None:
        source.parent.mkdir()
        source.write_bytes(regular_file(task / 'private/test_source.py', task))
        import tomllib

        checkpoints = tomllib.loads(regular_file(task / 'task.toml', task).decode())['metadata'].get('checkpoints', 3)
        dump(folder / 'setup-manifest.json', {'sha256': digest(source.read_bytes()), 'checkpoint': checkpoints})
    args = ['--arm', arm, '--mode', 'execute', *browser_args(config)]

    def create(suffix, *command):
        name = prefix + '-' + suffix
        docker('create', '--name', name, *command)
        containers.append((name, suffix))
        return name

    try:
        if digest(regular_file(artifact, artifact.parent, 65536)) != artifact_hash:
            raise ValueError('artifact changed after sealing')
        if (
            references is None
            or reference_digest(references, (config['viewport_width'], config['viewport_height'])) != references_hash
        ):
            raise ValueError('references changed after sealing')
        for network in (capture_net, client_net):
            docker('network', 'create', '--internal', network)
            networks.append(network)
        app = create(
            'app',
            '--network',
            capture_net,
            '--network-alias',
            'app',
            *relay_args(config['platform']),
            *app_isolation(task, config),
            *app_mounts(task, variant, config['platform']),
            config['app_image'],
        )
        mobile_session = start_app(task, variant, app, folder, config['platform'])
        dump(folder / 'app-container.json', inspect(app))
        from gui_agent_bench.applications import record_app

        record_app(task, folder, app, capture_net)
        if config['platform'] == 'tv':
            from gui_agent_bench.tv_session import record_app as record_tv

            record_tv(task, folder, app, capture_net)
        broker = create(
            'browser',
            '--network',
            capture_net,
            *isolation(memory='2g'),
            *(mount(source, '/setup/source.py') if source else []),
            *mount(references, '/references'),
            '--entrypoint',
            'python',
            ORACLE_BROWSER_IMAGE,
            '-m',
            'gui_agent_bench.oracle_broker',
            *args,
        )
        docker('network', 'connect', '--alias', 'browser', client_net, broker)
        docker('start', broker)
        ready = create(
            'ready',
            '--network',
            client_net,
            *isolation(memory='256m'),
            '--entrypoint',
            'python',
            WORKER_IMAGE,
            '-m',
            'gui_agent_bench.readiness',
            '--arm',
            arm,
            '--execute',
            '--platform',
            config['platform'],
            '--profile',
            config['environment_profile'],
            '--timeout',
            str(config['reference_timeout_sec']),
        )
        docker('start', '-a', ready, timeout=config['reference_timeout_sec'] + 10)
        if inspect(ready)['State']['ExitCode'] != 0:
            raise Failure('app_not_ready')
        details = inspect(broker)
        audit_broker(details, client_net, capture_net, source, references)
        audit_oracle_broker(details, arm, 'execute')
        dump(folder / 'broker-container.json', details)
        runner = create(
            'executor',
            '--network',
            client_net,
            *isolation(memory='128m'),
            '--pids-limit',
            '32',
            *mount(artifact, '/artifact/' + artifact.name),
            ORACLE_IMAGE,
            *(['--kind', 'test'] if full_test else []),
        )
        details = inspect(runner)
        network = json.loads(docker('network', 'inspect', client_net))[0]
        dump(folder / 'executor-container.json', details)
        dump(folder / 'executor-network.json', network)
        dump(folder / 'isolation.json', audit_execution(details, network, artifact))
        failure = None
        termination_causes = []
        phase, operation = ('execution', 'process')
        start = time.monotonic()
        with (folder / 'stdout.log').open('wb') as stdout, (folder / 'stderr.log').open('wb') as stderr:
            process = subprocess.Popen(['docker', 'start', '-a', runner], stdout=stdout, stderr=stderr)
            while process.poll() is None:
                if time.monotonic() - start > timeout:
                    failure = 'TIMEOUT'
                    if failure not in termination_causes:
                        termination_causes.append(failure)
                if sum(((folder / f).stat().st_size for f in ('stdout.log', 'stderr.log'))) > 1000000:
                    failure = 'OUTPUT_LIMIT'
                    if failure not in termination_causes:
                        termination_causes.append(failure)
                if failure:
                    docker('kill', runner, check=False)
                    process.wait(timeout=15)
                    break
                time.sleep(0.1)
        state = inspect(runner)['State']
        dump(folder / 'executor-state.json', state)
        if sum(((folder / f).stat().st_size for f in ('stdout.log', 'stderr.log'))) > 1000000:
            failure = 'OUTPUT_LIMIT'
            if failure not in termination_causes:
                termination_causes.append(failure)
        if state.get('OOMKilled'):
            failure = 'RESOURCE_LIMIT'
            termination_causes.append(failure)
        if not inspect(broker)['State']['Running']:
            failure = 'INFRA_ERROR'
            termination_causes.append(failure)
        dump(
            folder / 'termination.json', {'failure': failure, 'causes': termination_causes, 'timeout_seconds': timeout}
        )
        records = [json.loads(line) for line in docker('logs', broker).splitlines()]
        result.update(
            classify(records, state['ExitCode'], failure, full_test=full_test, termination_causes=termination_causes)
        )
        result['elapsed_seconds'] = round(time.monotonic() - start, 3)
        result['exit_code'] = state['ExitCode']
        collect_files(broker, folder / 'image-assertions', 'image-assertions')
    except Exception as exc:
        previous = result.get('diagnostics', {}).get('issues', [])
        result.update(
            outcome='SETUP_ERROR',
            assertions=[],
            reason='Execution preparation or collection failed.',
            diagnostics=diagnostics(previous + [issue(exc, phase=phase, operation=operation, impact='zero_credit')]),
        )
    finally:
        from gui_agent_bench.controller_cleanup import finalize_resources

        targets = [
            (name, folder / (label + '.log'), True) for name, label in reversed(containers) if label != 'executor'
        ]
        cleanup_issues = finalize_resources(
            mobile_session, [name for name, _ in containers], networks, targets, folder, docker
        )
        if cleanup_issues:
            previous = result.get('diagnostics', {}).get('issues', [])
            result.update(outcome='ERROR', cleanup_failed=True, diagnostics=diagnostics(previous + cleanup_issues))
        if (folder / 'browser.log').exists() and result['outcome'] == 'SETUP_ERROR' and ('exit_code' not in result):
            startup = []
            for line in (folder / 'browser.log').read_text().splitlines():
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    startup.append(record)
            result['diagnostics'] = diagnostics(
                record_issues(startup, phase='setup', source='browser.log')
                + result.get('diagnostics', {}).get('issues', [])
            )
        dump(folder / 'result.json', result)
    return result


def verify_pair(task, artifact, folder, arm, timeout=None, references=None, deadline=None):
    """Seal one artifact and execute it EXECUTIONS_PER_VERSION times on each fresh version.

    ``deadline`` is the monotonic end of the enclosing paired attempt; later
    executions receive only the remaining time and fail by timeout after it.
    """
    from gui_agent_bench.actions import ACTION_CONTRACT

    folder.mkdir(parents=True, exist_ok=True)
    planned = [{'id': uuid.uuid4().hex[:16], 'variant': v} for v in planned_variants()]
    plan = {
        'arm': arm,
        'planned_executions': len(planned),
        'executions_per_version': EXECUTIONS_PER_VERSION,
        'executions': planned,
        'sha256': None,
        'visual_api': VERSION,
        'comparator': COMPARATOR,
        'action_contract': ACTION_CONTRACT,
        'failure_contract': FAILURE_VERSION,
        'environment_contract': ENVIRONMENT_VERSION,
        'environment_profile': runtime(task)['environment_profile'],
    }
    dump(folder / 'plan.json', plan)
    write_result(folder / 'logs/verifier', status='planned', planned_executions=len(planned), completed_executions=0)
    full_test = arm.startswith('test_')
    operation = 'validate_task'
    results = []
    timeout = timeout if timeout is not None else execution_timeout(arm)
    try:
        sealed = folder / 'sealed' / artifact_name(arm)
        if runtime(task)['platform'] == 'tv':
            from gui_agent_bench.tv_import import verify_task
            from gui_agent_bench.tv import TV_ARMS

            verify_task(task)
            if arm not in TV_ARMS:
                raise ValueError('TV UI arms are unavailable')
        if runtime(task)['platform'] == 'mobile':
            from gui_agent_bench.task_package import verify

            verify(task)
        operation = 'seal_submission'
        sha = seal(artifact, sealed, 'test' if full_test else 'check')
        config = runtime(task)
        reference_dir = folder / 'sealed/references'
        reference_sha = seal_references(
            references, reference_dir, (config['viewport_width'], config['viewport_height'])
        )
        bundle_sha = digest((sha + ':' + reference_sha).encode())
        dump(
            folder / 'submission.json',
            {
                'sha256': sha,
                'sealed': True,
                'present': True,
                'references_sha256': reference_sha,
                'bundle_sha256': bundle_sha,
            },
        )
        operation = 'validate_labels'
        labels = json.loads(regular_file(task / 'private/labels.json', task))
        if labels != {'correct': 'PASS', 'faulty': 'FAIL'}:
            raise ValueError('unsupported paired labels')
        dump(
            folder / 'plan.json',
            {**plan, 'sha256': sha, 'references_sha256': reference_sha, 'bundle_sha256': bundle_sha},
        )
        results = []
        for entry in planned:
            limit = timeout if deadline is None else max(1, min(timeout, int(deadline - time.monotonic())))
            result = execute(
                task,
                sealed,
                folder / 'executions' / entry['id'],
                entry['variant'],
                arm,
                sha,
                limit,
                reference_dir,
                reference_sha,
            )
            results.append({**result, 'variant': entry['variant']})
        verdict = pair_result(results)
        return write_result(
            folder / 'logs/verifier',
            **verdict,
            submission_sha256=sha,
            references_sha256=reference_sha,
            bundle_sha256=bundle_sha,
            planned_executions=len(planned),
            completed_executions=len(results),
        )
    except Exception as exc:
        cause = (
            (
                'missing_submission'
                if isinstance(exc, FileNotFoundError) and (not artifact.exists())
                else 'malformed_submission'
            )
            if operation == 'seal_submission'
            else 'infrastructure_error'
        )
        return write_result(
            folder / 'logs/verifier',
            status='invalid_submission',
            reason='Pair could not be prepared.',
            diagnostics=diagnostics(
                [item for result in results for item in result.get('diagnostics', {}).get('issues', [])]
                + [
                    issue(
                        Failure(cause),
                        phase='sealing' if operation == 'seal_submission' else 'setup',
                        operation=operation,
                        impact='zero_credit',
                    )
                ]
            ),
            executions=results,
            planned_executions=len(planned),
            completed_executions=len(results),
        )
