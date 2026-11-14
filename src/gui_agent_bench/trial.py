"""Trusted evaluation controller. Private task data stay outside agent workspaces."""

import json
import os
from pathlib import Path
import time
import tomllib
import uuid
from gui_agent_bench.audit import audit_broker
from gui_agent_bench.docker import AGENT_IMAGE, WORKER_IMAGE, ORACLE_BROWSER_IMAGE, docker, inspect, isolation, mount
from gui_agent_bench.io import digest, dump, regular_file
from gui_agent_bench.materialize import materialize
from gui_agent_bench.runners.opencode import VERSION
from gui_agent_bench.runners.registry import ACCOUNT_RUNNERS, BILLING_MODES
from gui_agent_bench.verifier.judge import aggregate, write_result
from gui_agent_bench.task_runtime import runtime, app_isolation, browser_args
from gui_agent_bench.task_package import discover, verify
from gui_agent_bench.arms import ARM_IDS, generated, artifact_name, abi
from gui_agent_bench.budgets import PAIRED_ATTEMPT_SECONDS, planned_variants
from gui_agent_bench.mobile_session import relay_args, start_app
from gui_agent_bench.applications import app_mounts
from gui_agent_bench.actions import ACTION_CONTRACT
from gui_agent_bench.environment import VERSION as ENVIRONMENT_VERSION
from gui_agent_bench.failures import Failure, issue, diagnostics, record_issues, VERSION as FAILURE_VERSION


def _prepare_verifier_logs(path: Path) -> None:
    """Permit the fixed unprivileged worker UID to replace planned results."""
    path.chmod(511)
    for name in ('reward.txt', 'reward.json', 'metrics.json'):
        result = path / name
        if result.is_symlink() or not result.is_file():
            raise ValueError('planned verifier result is missing or invalid')
        result.chmod(438)


def _run_trial(
    root: Path,
    task: Path,
    directory: Path,
    variant: str,
    model: str,
    timeout: int,
    fixture_verdict: str,
    fixture_probe: bool,
    arm='judge_visual',
    oracle_control='auto',
    *,
    agent_spec=None,
    credential_source=None,
) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    verifier_logs = directory / 'logs/verifier'
    write_result(verifier_logs, status='planned')
    containers, networks = ([], [])
    mobile_session = None
    from gui_agent_bench.runners.registry import resolve

    agent_spec = agent_spec or resolve(model)
    provider_name, model_id = model.split('/', 1)
    prefix = 'gab-' + directory.name
    evidence, gold = (directory / 'capture', directory / 'gold')
    workspace, output, config_dir = (directory / 'workspace', directory / 'output', directory / 'config')
    artifact = directory / 'sealed'
    app_runtime = runtime(task)
    phase, operation = ('setup', 'configure_runtime')
    viewport_args = browser_args(app_runtime)
    for path in (evidence, gold, output, config_dir, artifact):
        path.mkdir()
    for path in (evidence, gold, output):
        path.chmod(511)
    # The capture container writes its screenshots as the image's user. Creating
    # their folder here keeps it owned by the host user, so a finished run can
    # be deleted without elevated privileges.
    (evidence / 'screenshots').mkdir()
    (evidence / 'screenshots').chmod(511)
    _prepare_verifier_logs(verifier_logs)

    def create(name, *args, env=None):
        containers.append(name)
        docker('create', '--name', name, '--label', f'gui-agent-bench.trial={directory.name}', *args, env=env)
        return name

    def start(name):
        docker('start', name)

    def complete(name, limit=60):
        docker('start', '-a', name, timeout=limit)
        if inspect(name)['State']['ExitCode'] != 0:
            raise Failure('infrastructure_error')

    try:
        if model not in {'fixture/scripted', 'reference/solution'}:
            operation = 'fairness_qualification'
            from gui_agent_bench.fairness import require as require_fairness

            try:
                require_fairness(root, task.relative_to(root / 'tasks').as_posix())
            except (ValueError, OSError) as exc:
                raise Failure('capability_unavailable') from exc
        if provider_name == 'openrouter' and (not os.environ.get('OPENROUTER_API_KEY')):
            raise ValueError('OPENROUTER_API_KEY is required in the environment')
        if agent_spec.runner == 'opencode':
            version = docker('run', '--rm', '--network', 'none', *isolation(), AGENT_IMAGE, '--version')
            if version != VERSION:
                raise ValueError('unverified OpenCode version')
        for suffix in ('capture', 'inference'):
            name = prefix + '-' + suffix
            docker('network', 'create', '--internal', '--label', f'gui-agent-bench.trial={directory.name}', name)
            networks.append(name)
        capture_net, agent_net = networks
        operation = 'start_app'
        app = create(
            prefix + '-app',
            '--network',
            capture_net,
            '--network-alias',
            'app',
            *relay_args(app_runtime['platform']),
            *app_isolation(task, app_runtime),
            *app_mounts(task, variant, app_runtime['platform']),
            app_runtime['app_image'],
        )
        mobile_session = start_app(task, variant, app, directory, app_runtime['platform'])
        dump(directory / 'app-container.json', inspect(app))
        from gui_agent_bench.applications import record_app

        record_app(task, directory, app, capture_net)
        if app_runtime['platform'] == 'tv':
            from gui_agent_bench.tv_session import record_app as record_tv

            record_tv(task, directory, app, capture_net)
        operation = 'capture_reference'
        capture = create(
            prefix + '-capture',
            '--network',
            capture_net,
            *isolation(memory='2g'),
            *mount(task / 'private', '/private'),
            *mount(evidence, '/evidence', writable=True),
            *mount(gold, '/gold', writable=True),
            '--entrypoint',
            'python',
            WORKER_IMAGE,
            '/private/gold_test.py',
            '--url',
            'http://app:8000/',
            '--evidence',
            '/evidence',
            '--result',
            '/gold/gold-result.json',
            *viewport_args,
        )
        dump(directory / 'capture-container.json', inspect(capture))
        complete(capture, limit=app_runtime['reference_timeout_sec'])
        labels = json.loads(regular_file(task / 'private/labels.json', task))
        if json.loads(regular_file(gold / 'gold-result.json', gold)) != {'verdict': labels[variant]}:
            raise ValueError('gold outcome does not match the admitted private label')
        dump(gold / 'source-manifest.json', {'sha256': digest(regular_file(task / 'private/test_source.py', task))})
        if arm == 'judge_visual':
            if mobile_session:
                mobile_session.close()
                mobile_session = None
            docker('stop', '--time', '1', app)
        else:
            operation = 'prepare_broker'
            setup_source = None
            if arm.startswith('oracle_'):
                setup_source = directory / 'setup/source.py'
                setup_source.parent.mkdir()
                setup_source.write_bytes(regular_file(task / 'private/test_source.py', task))
                broker = create(
                    prefix + '-browser',
                    '--network',
                    capture_net,
                    *isolation(memory='2g'),
                    *mount(setup_source, '/setup/source.py'),
                    '--entrypoint',
                    'python',
                    ORACLE_BROWSER_IMAGE,
                    '-m',
                    'gui_agent_bench.oracle_broker',
                    '--arm',
                    arm,
                    '--mode',
                    'author',
                    *viewport_args,
                )
            elif arm.startswith('test_'):
                broker = create(
                    prefix + '-browser',
                    '--network',
                    capture_net,
                    *isolation(memory='2g'),
                    '--entrypoint',
                    'python',
                    ORACLE_BROWSER_IMAGE,
                    '-m',
                    'gui_agent_bench.oracle_broker',
                    '--arm',
                    arm,
                    '--mode',
                    'author',
                    *viewport_args,
                )
            else:
                broker = create(
                    prefix + '-browser',
                    '--network',
                    capture_net,
                    *isolation(memory='2g'),
                    WORKER_IMAGE,
                    '_broker',
                    *viewport_args,
                )
            docker('network', 'connect', '--alias', 'browser', agent_net, broker)
            start(broker)
            ready = create(
                prefix + '-ready',
                '--network',
                agent_net,
                *isolation(memory='256m'),
                '--entrypoint',
                'python',
                WORKER_IMAGE,
                '-m',
                'gui_agent_bench.readiness',
                '--arm',
                arm,
                '--platform',
                app_runtime['platform'],
                '--profile',
                app_runtime['environment_profile'],
                '--timeout',
                str(app_runtime['reference_timeout_sec']),
            )
            complete(ready, limit=app_runtime['reference_timeout_sec'] + 10)
            broker_details = inspect(broker)
            dump(directory / 'broker-container.json', broker_details)
            dump(
                directory / 'broker-isolation.json', audit_broker(broker_details, agent_net, capture_net, setup_source)
            )
            if generated(arm):
                from gui_agent_bench.verifier.oracle import audit_oracle_broker

                audit_oracle_broker(broker_details, arm, 'author')
        operation = 'materialize_workspace'
        manifest = materialize(
            root,
            task,
            evidence,
            workspace,
            arm,
            app_runtime['platform'],
            viewport=(app_runtime['viewport_width'], app_runtime['viewport_height']),
        )
        tool_profile = 'generic'
        dump(directory / 'workspace-manifest.json', manifest)
        operation = 'configure_agent'
        from gui_agent_bench.runners.base import AuthoringContext

        context = AuthoringContext(
            directory.name,
            arm,
            app_runtime['platform'],
            (app_runtime['viewport_width'], app_runtime['viewport_height']),
            workspace,
            manifest,
            output,
            config_dir,
            directory / 'logs/agent',
            agent_net,
            None if arm == 'judge_visual' else broker,
            timeout,
            tool_profile,
        )
        if model == 'fixture/scripted' and oracle_control not in {'pass', 'fail', 'crash', 'missing', 'forbidden'}:
            from dataclasses import replace
            from gui_agent_bench.task_package import load_control
            from gui_agent_bench.reference_controls import register_task

            context = replace(context, fixture_record=load_control(task))
            oracle_control = register_task(task)
        phase, operation = ('authoring', 'agent_process')
        if agent_spec.runner == 'codex':
            from gui_agent_bench.runners.codex import launch

            launch(root, agent_spec, context, credential_source, containers, networks)
            summary = json.loads((directory / 'logs/agent/summary.json').read_text())
        elif agent_spec.runner == 'cursor':
            from gui_agent_bench.runners.cursor import launch

            summary = launch(root, agent_spec, context, credential_source, containers, networks)
        elif agent_spec.runner == 'claude':
            from gui_agent_bench.runners.claude import launch

            summary = launch(root, agent_spec, context, credential_source, containers, networks)
        else:
            from gui_agent_bench.runners.opencode_adapter import author

            summary = author(
                root,
                context,
                model,
                fixture_verdict,
                fixture_probe,
                oracle_control,
                create,
                start,
                variant=agent_spec.reasoning_effort,
            )
        if arm != 'judge_visual' and (not inspect(broker)['State']['Running']):
            raise Failure('infrastructure_error')
        dump(directory / 'logs/agent/summary.json', summary)
        if arm != 'judge_visual':
            from gui_agent_bench.authoring_recovery import audit_recovery_events

            recovery_records = [json.loads(line) for line in docker('logs', broker).splitlines()]
            audit_recovery_events(recovery_records, app_runtime['platform'])
        phase, operation = ('sealing', 'collect_submission')
        filename = artifact_name(arm)
        submitted = output / filename
        reference_sha = None
        if generated(arm):
            from gui_agent_bench.visual import reference_digest, collect_files

            collect_files(broker, artifact / 'references', 'references')
            reference_sha = reference_digest(
                artifact / 'references', (app_runtime['viewport_width'], app_runtime['viewport_height'])
            )
        if submitted.exists() or submitted.is_symlink():
            try:
                data = regular_file(submitted, output, 65536 if generated(arm) else 16384)
            except ValueError as exc:
                # Oversized, linked or non-regular: the agent's artifact breaks its contract.
                phase, operation = ('sealing', 'validate_submission')
                raise Failure('malformed_submission') from exc
            (artifact / filename).write_bytes(data)
            dump(
                directory / 'submission.json',
                {
                    'sha256': digest(data),
                    'sealed': True,
                    'present': True,
                    **({'references_sha256': reference_sha} if reference_sha else {}),
                },
            )
        else:
            dump(directory / 'submission.json', {'sha256': None, 'sealed': True, 'present': False})
        if generated(arm):
            return {'status': 'authored', 'reward': 0}
        phase, operation = ('grading', 'judge_submission')
        verifier = create(
            prefix + '-verifier',
            '--network',
            'none',
            *isolation(memory='512m'),
            *mount(artifact, '/artifact'),
            *mount(task / 'private', '/private'),
            *mount(task / 'tests', '/tests'),
            *mount(verifier_logs, '/logs/verifier', writable=True),
            '--entrypoint',
            'sh',
            WORKER_IMAGE,
            '/tests/test.sh',
            variant,
        )
        complete(verifier)
        return json.loads((verifier_logs / 'metrics.json').read_text())
    except Exception as exc:
        issues = getattr(exc, 'diagnostic_issues', None) or [
            issue(exc, phase=phase, operation=operation, impact='zero_credit')
        ]
        return write_result(
            verifier_logs, status='trial_error', reason=issues[0]['message'], diagnostics=diagnostics(issues)
        )
    finally:
        from gui_agent_bench.controller_cleanup import CleanupFailure, finalize_resources
        import sys

        preceding_error = sys.exc_info()[1]
        targets = []
        for suffix in ('app', 'capture'):
            if prefix + '-' + suffix in containers:
                targets.append((prefix + '-' + suffix, directory / 'logs' / (suffix + '.log'), True))
        for suffix, filename in (('provider', 'provider.ndjson'), ('browser', 'browser.ndjson')):
            if prefix + '-' + suffix in containers:
                targets.append((prefix + '-' + suffix, directory / 'logs' / filename, False))
        cleanup_issues = finalize_resources(mobile_session, containers, networks, targets, directory, docker)
        if cleanup_issues:
            previous = []
            saved = verifier_logs / 'metrics.json'
            if saved.exists():
                try:
                    previous = json.loads(saved.read_text()).get('diagnostics', {}).get('issues', [])
                except (ValueError, OSError) as error:
                    previous.append(issue(error, phase='cleanup', operation='read_metrics', impact='zero_credit'))
            write_result(
                verifier_logs,
                status='trial_error',
                reward=0,
                reason=cleanup_issues[0]['message'],
                diagnostics=diagnostics(previous + cleanup_issues),
            )
            failure = CleanupFailure(previous + cleanup_issues)
            if preceding_error is not None and (not isinstance(preceding_error, Exception)):
                raise BaseExceptionGroup('Trial interruption and cleanup failed', [preceding_error, failure]) from None
            raise failure from preceding_error


def run_trial(root, task, directory, *args, **kwargs):
    """Collect diagnostics after cleanup exported the broker/provider records."""
    try:
        result = _run_trial(root, task, directory, *args, **kwargs)
    except Exception as exc:
        previous = []
        saved = directory / 'logs/verifier/metrics.json'
        if saved.exists():
            try:
                previous = json.loads(saved.read_text()).get('diagnostics', {}).get('issues', [])
            except (ValueError, OSError):
                pass
        result = {
            'status': 'trial_error',
            'reward': 0,
            'diagnostics': diagnostics(
                getattr(exc, 'diagnostic_issues', None)
                or previous + [issue(exc, phase='controller', operation='trial_lifecycle', impact='zero_credit')]
            ),
        }
    issues = []
    for source, phase in [('logs/browser.ndjson', 'authoring'), ('logs/provider.ndjson', 'inference')]:
        path = directory / source
        if path.exists():
            records = []
            for index, line in enumerate(path.read_text(encoding='utf-8').splitlines()):
                try:
                    value = json.loads(line)
                except ValueError:
                    issues.append(
                        issue(
                            Failure('unknown_operation_error'),
                            phase=phase,
                            operation='read_log',
                            impact='feedback',
                            source={'file': source, 'record_index': index},
                        )
                    )
                    records.append({})
                    continue
                if isinstance(value, dict):
                    records.append(value)
                else:
                    records.append({})
            issues.extend(record_issues(records, phase=phase, source=source))
    result['diagnostics'] = diagnostics(issues + result.get('diagnostics', {}).get('issues', []))
    return write_result(directory / 'logs/verifier', **{k: v for k, v in result.items() if k != 'planned_trials'})


def run(
    root: Path,
    task_id: str,
    arm: str,
    variant: str,
    model: str,
    output: Path,
    timeout: int,
    fixture_verdict: str,
    fixture_probe: bool,
    allow_candidate=False,
    oracle_control='auto',
    *,
    agent_spec=None,
    credential_source=None,
) -> dict:
    if task_id not in discover(root) or arm not in ARM_IDS:
        raise ValueError('task or arm is not admitted')
    from gui_agent_bench.runners.registry import resolve, fingerprint

    agent_spec = agent_spec or resolve(model, fixture_probe=fixture_probe)
    if agent_spec != resolve(
        model,
        reasoning_effort=agent_spec.reasoning_effort or 'medium',
        fixture_probe=fixture_probe,
        variant=agent_spec.reasoning_effort if agent_spec.runner == 'opencode' else None,
    ):
        raise ValueError('Agent specification differs from requested model')
    task = root / 'tasks' / task_id
    metadata = tomllib.loads((task / 'task.toml').read_text())['metadata']
    if metadata['status'] not in {'smoke', 'component', 'admitted', 'example'} and (
        not (allow_candidate and metadata['status'] == 'candidate')
    ):
        raise ValueError('task is not admitted; use --allow-candidate only for review runs')
    if arm not in metadata['eligible_arms']:
        raise ValueError('task is not admitted for this arm')
    verify(task)
    if model == 'reference/solution':
        from gui_agent_bench.reference import run as run_reference

        return run_reference(root, task, arm, variant, output)
    oracle = generated(arm)
    if oracle and variant != 'pair':
        raise ValueError('generated programs always verify both variants; use --variant pair')
    variants = ['correct'] if oracle else ['correct', 'faulty'] if variant == 'pair' else [variant]
    directory = output.resolve() / uuid.uuid4().hex[:16]
    directory.mkdir(parents=True, exist_ok=False)
    planned = [{'id': uuid.uuid4().hex[:16], 'variant': name} for name in variants]
    variant_record = (
        {'model_variant': agent_spec.reasoning_effort}
        if agent_spec.runner == 'opencode' and agent_spec.reasoning_effort
        else {}
    )
    dump(
        directory / 'plan.json',
        {
            'task': task_id,
            'arm': arm,
            'model': model,
            **variant_record,
            **(
                {
                    'runner': agent_spec.runner,
                    'runner_version': __import__(
                        'gui_agent_bench.runners.' + agent_spec.runner + '_config', fromlist=['VERSION']
                    ).VERSION,
                    'agent_spec': agent_spec.record(),
                    'configuration_sha256': fingerprint(agent_spec.record()),
                }
                if agent_spec.runner in ACCOUNT_RUNNERS
                else {}
            ),
            'action_contract': ACTION_CONTRACT,
            'failure_contract': FAILURE_VERSION,
            'environment_contract': ENVIRONMENT_VERSION,
            'environment_profile': runtime(task)['environment_profile'],
            'platform': metadata['platform'],
            'domain': metadata.get('domain', metadata['platform']),
            'task_status': metadata['status'],
            'research_core': False,
            'fixture': model.startswith('fixture/'),
            'planned_trials': len(planned),
            'trials': planned,
            **(
                {
                    'planned_artifacts': 1,
                    'planned_executions': len(planned_variants()),
                    'authoring_state': 'correct',
                    'abi': abi(arm, metadata['platform']),
                }
                if oracle
                else {}
            ),
        },
    )
    results = []
    for entry in planned:
        write_result(directory / 'trials' / entry['id'] / 'logs/verifier', status='planned')
    dump(
        directory / 'summary.json',
        {**aggregate([], len(planned), variant == 'pair'), 'status': 'running', 'model': model, 'research_core': False},
    )
    if agent_spec.runner in ACCOUNT_RUNNERS:
        from gui_agent_bench.preflight import check

        if agent_spec.runner == 'codex':
            from gui_agent_bench.runners.codex_config import resolved
            from gui_agent_bench.runners.codex import image_ids
        else:
            from importlib import import_module

            resolved = import_module('gui_agent_bench.runners.' + agent_spec.runner + '_config').resolved
            image_ids = import_module('gui_agent_bench.runners.' + agent_spec.runner).image_ids
        cell = dict(task=task_id, arm=arm, model=model, fixture_program=oracle_control, agent_spec=agent_spec.record())
        report = check(root, {'cells': [cell]}, credential_source=credential_source)
        dump(directory / 'preflight.json', report)
        if report['status'] != 'passed':
            for entry in planned:
                write_result(
                    directory / 'trials' / entry['id'] / 'logs/verifier',
                    status='trial_error',
                    diagnostics=report['diagnostics'],
                )
            summary = {
                **aggregate([], len(planned), variant == 'pair'),
                'status': 'preflight_failed',
                'run_directory': str(directory),
                'model': model,
                'runner': agent_spec.runner,
                'provider_cost_usd': None,
                'billing_mode': BILLING_MODES[agent_spec.runner],
                'preflight': report,
            }
            dump(directory / 'summary.json', summary)
            print(json.dumps(summary, indent=2), flush=True)
            return summary
        contract = resolved(root, [agent_spec], [cell], image_ids(), timeout)
        dump(directory / 'resolved-plan.json', contract)
        saved_plan = json.loads((directory / 'plan.json').read_text())
        saved_plan['resolved_plan_sha256'] = fingerprint(contract)
        dump(directory / 'plan.json', saved_plan)
    # One wall-clock budget covers the whole paired attempt: environment
    # preparation, every agent session and the evaluation of its artifact.
    deadline = time.monotonic() + PAIRED_ATTEMPT_SECONDS
    for entry in planned:
        print(f"Running trial {entry['id']}", flush=True)
        session_timeout = max(1, min(timeout, int(deadline - time.monotonic())))
        result = run_trial(
            root,
            task,
            directory / 'trials' / entry['id'],
            entry['variant'],
            model,
            session_timeout,
            fixture_verdict,
            fixture_probe,
            arm,
            oracle_control,
            **(
                {'agent_spec': agent_spec, 'credential_source': credential_source}
                if agent_spec.runner in ACCOUNT_RUNNERS
                else {'agent_spec': agent_spec} if variant_record else {}
            ),
        )
        if oracle and result['status'] == 'authored':
            from gui_agent_bench.verifier.oracle import verify_pair

            trial_dir = directory / 'trials' / entry['id']
            author_diagnostics = result['diagnostics']['issues']
            result = verify_pair(
                task,
                trial_dir / 'sealed' / artifact_name(arm),
                trial_dir / 'verification',
                arm,
                references=trial_dir / 'sealed/references',
                deadline=deadline,
            )
            result['diagnostics'] = diagnostics(author_diagnostics + result['diagnostics']['issues'])
            fields = {k: v for k, v in result.items() if k not in {'status', 'reward', 'planned_trials'}}
            write_result(trial_dir / 'logs/verifier', status=result['status'], reward=result['reward'], **fields)
        results.append(result)
        print(f"Trial {entry['id']}: {result['status']}, reward={result['reward']}", flush=True)
        if result.get('reason'):
            print(result['reason'], flush=True)
        dump(
            directory / 'summary.json',
            {
                **aggregate(results, len(planned), variant == 'pair'),
                'status': 'running',
                'model': model,
                'research_core': False,
            },
        )
    summary = {
        **aggregate(results, len(planned), variant == 'pair'),
        'run_directory': str(directory),
        'action_contract': ACTION_CONTRACT,
        'failure_contract': FAILURE_VERSION,
        'environment_contract': ENVIRONMENT_VERSION,
        'environment_profile': runtime(task)['environment_profile'],
        'status': 'complete',
        'model': model,
        'fixture': model.startswith('fixture/'),
        'research_core': False,
    }
    if oracle:
        summary.update(
            planned_artifacts=1,
            planned_executions=len(planned_variants()),
            paired_score=results[0]['reward'],
            authoring_state='correct',
            abi=abi(arm, metadata['platform']),
        )
    usage = []
    for path in directory.glob('trials/*/logs/provider.ndjson'):
        for line in path.read_text().splitlines():
            try:
                item = json.loads(line)
                if 'usage' in item:
                    usage.append(item['usage'])
            except ValueError:
                pass
    summary['provider_cost_usd'] = round(sum((item.get('cost') or 0 for item in usage)), 9) if usage else None
    summary.update(variant_record)
    if agent_spec.runner in ACCOUNT_RUNNERS:
        from importlib import import_module

        summary.update(
            runner=agent_spec.runner,
            runner_version=import_module('gui_agent_bench.runners.' + agent_spec.runner + '_config').VERSION,
            agent_spec=agent_spec.record(),
            provider_cost_usd=None,
            billing_mode=BILLING_MODES[agent_spec.runner],
            budget_profile=agent_spec.budget_profile,
            resolved_plan_sha256=fingerprint(contract),
        )
    dump(directory / 'summary.json', summary)
    print(json.dumps(summary, indent=2), flush=True)
    return summary
