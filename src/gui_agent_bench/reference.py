"""Privileged known-solution runs, deliberately outside the evaluated agent.

Labels may be read here, never by OpenCode or an inference provider. Written
Python still runs through the unchanged isolated paired verifier. No reward is
assigned merely because this is a reference run.
"""

import ast
import json
import uuid
from gui_agent_bench.arms import artifact_name, generated, abi
from gui_agent_bench.budgets import planned_variants
from gui_agent_bench.actions import ACTION_CONTRACT
from gui_agent_bench.environment import VERSION as ENVIRONMENT_VERSION
from gui_agent_bench.failures import Failure, diagnostics, issue, VERSION as FAILURE_VERSION
from gui_agent_bench.io import digest, dump, regular_file, strict_json
from gui_agent_bench.task_runtime import runtime, browser_args
from gui_agent_bench.verifier.judge import aggregate, grade, write_result

MODEL = 'reference/solution'
VERSION = 'reference-run-v1'
SCOPE = 'Privileged known-solution validation; no evaluated agent or model score'
# Aliases remain available for tooling that inspects the included examples.
from gui_agent_bench.task_package import ROOT, discover, task_path, integration

CONTROLS = {
    identifier: integration(task_path(ROOT, identifier)).get('reference_alias', identifier)
    for identifier in discover(ROOT)
}


def control_for(task_id, root=ROOT):
    from gui_agent_bench.reference_controls import register_task

    return register_task(task_path(root, task_id))


def source_for(task_id, arm, root=ROOT):
    if not generated(arm):
        return None
    from gui_agent_bench.reference_controls import CONTROLS as controls

    control = control_for(task_id, root)
    return controls[control].source(control, arm)


def needs_reference_images(arm, code):
    """UI references may choose image assertions under the existing superset."""
    return arm.endswith('_visual') or any(
        (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and (node.func.value.id == 'page')
            and (node.func.attr == 'expect_image')
            for node in ast.walk(ast.parse(code))
        )
    )


def validate(task_id, arm, root=ROOT):
    """Static preparation check only; no app, agent, or reference execution."""
    from gui_agent_bench.arms import ARM_IDS

    if arm not in ARM_IDS:
        raise ValueError('Reference arm is unavailable')
    from gui_agent_bench.task_package import metadata

    task = task_path(root, task_id)
    if arm not in metadata(task)['metadata']['eligible_arms']:
        raise ValueError('Reference arm is unavailable for this task')
    source_for(task_id, arm, root)


def prepare_references(root, task, folder, arm):
    """Capture public images in a fresh correct app, without an agent/provider.

    Oracle setup stops before the private behavioral assertion, exactly as for
    ordinary oracle authoring. Full-test preparation follows the hand-written
    visual journey. Nothing learns or updates references during paired grading.
    """
    from gui_agent_bench.audit import audit_broker
    from gui_agent_bench.docker import docker, inspect, isolation, mount, WORKER_IMAGE, ORACLE_BROWSER_IMAGE
    from gui_agent_bench.mobile_session import relay_args, start_app
    from gui_agent_bench.task_runtime import app_isolation
    from gui_agent_bench.applications import app_mounts
    from gui_agent_bench.verifier.oracle import audit_oracle_broker
    from gui_agent_bench.visual import collect_files, reference_digest

    config = runtime(task)
    folder.mkdir(parents=True)
    prefix = 'gab-reference-' + uuid.uuid4().hex[:12]
    app_net, client_net = (prefix + '-capture', prefix + '-inference')
    containers, networks = ([], [])
    mobile_session = None
    source = None
    control = control_for(task.relative_to(root / 'tasks').as_posix(), root)
    if arm.startswith('oracle_'):
        source = folder / 'setup/source.py'
        source.parent.mkdir()
        source.write_bytes(regular_file(task / 'private/test_source.py', task))
        dump(folder / 'setup-manifest.json', {'sha256': digest(source.read_bytes())})

    def create(suffix, *arguments):
        name = prefix + '-' + suffix
        containers.append((name, suffix))
        docker('create', '--name', name, '--label', f'gui-agent-bench.reference={folder.parent.name}', *arguments)
        return name

    def complete(name, timeout):
        docker('start', '-a', name, timeout=timeout)
        if inspect(name)['State']['ExitCode'] != 0:
            raise Failure('app_not_ready')

    try:
        for network in (app_net, client_net):
            docker('network', 'create', '--internal', network)
            networks.append(network)
        app = create(
            'app',
            '--network',
            app_net,
            '--network-alias',
            'app',
            *relay_args(config['platform']),
            *app_isolation(task, config),
            *app_mounts(task, 'correct', config['platform']),
            config['app_image'],
        )
        mobile_session = start_app(task, 'correct', app, folder, config['platform'])
        dump(folder / 'app-container.json', inspect(app))
        from gui_agent_bench.applications import record_app

        record_app(task, folder, app, app_net)
        if config['platform'] == 'tv':
            from gui_agent_bench.tv_session import record_app as record_tv

            record_tv(task, folder, app, app_net)
        broker = create(
            'browser',
            '--network',
            app_net,
            *isolation(memory='2g'),
            *(mount(source, '/setup/source.py') if source else []),
            '--entrypoint',
            'python',
            ORACLE_BROWSER_IMAGE,
            '-m',
            'gui_agent_bench.oracle_broker',
            '--arm',
            arm,
            '--mode',
            'author',
            *browser_args(config),
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
            '--platform',
            config['platform'],
            '--profile',
            config['environment_profile'],
            '--timeout',
            str(config['reference_timeout_sec']),
        )
        complete(ready, config['reference_timeout_sec'] + 10)
        details = inspect(broker)
        dump(folder / 'broker-container.json', details)
        dump(folder / 'broker-isolation.json', audit_broker(details, client_net, app_net, source))
        audit_oracle_broker(details, arm, 'author')
        from gui_agent_bench.reference_controls import CONTROLS as controls

        record_path = folder / 'control.json'
        dump(record_path, controls[control].record)
        client = create(
            'preparer',
            '--network',
            client_net,
            *isolation(memory='256m'),
            *mount(record_path, '/control.json'),
            '--entrypoint',
            'python',
            WORKER_IMAGE,
            '-m',
            'gui_agent_bench.reference_capture',
            '--control',
            control,
            '--arm',
            arm,
            '--control-file',
            '/control.json',
        )
        dump(folder / 'preparer-container.json', inspect(client))
        complete(client, config['reference_timeout_sec'])
        references = folder / 'references'
        collect_files(broker, references, 'references')
        sha = reference_digest(references, (config['viewport_width'], config['viewport_height']))
        dump(
            folder / 'reference-manifest.json',
            {
                'version': VERSION,
                'control': control,
                'source': 'public authoring captures before paired grading',
                'references_sha256': sha,
                'agent_started': False,
                'provider_started': False,
            },
        )
        return references
    finally:
        from gui_agent_bench.controller_cleanup import CleanupFailure, finalize_resources
        import sys

        preceding_error = sys.exc_info()[1]
        targets = [(name, folder / (suffix + '.log'), True) for name, suffix in reversed(containers)]
        cleanup_issues = finalize_resources(
            mobile_session, [name for name, _ in containers], networks, targets, folder, docker
        )
        if cleanup_issues:
            previous = []
            if preceding_error is not None:
                previous = getattr(preceding_error, 'diagnostic_issues', None) or [
                    issue(preceding_error, phase='setup', operation='prepare_reference_images', impact='zero_credit')
                ]
            failure = CleanupFailure(previous + cleanup_issues)
            if preceding_error is not None and (not isinstance(preceding_error, Exception)):
                raise BaseExceptionGroup(
                    'Reference interruption and cleanup failed', [preceding_error, failure]
                ) from None
            raise failure from preceding_error


def run_trial(root, task, directory, variant, arm):
    directory.mkdir(parents=True, exist_ok=True)
    logs = directory / 'logs/verifier'
    write_result(logs, status='planned')
    output, sealed = (directory / 'output', directory / 'sealed')
    output.mkdir()
    sealed.mkdir()
    phase, operation = ('sealing', 'write_reference_solution')
    task_id = task.relative_to(root / 'tasks').as_posix()
    marker = {
        'version': VERSION,
        'model': MODEL,
        'scope': SCOPE,
        'agent_started': False,
        'provider_started': False,
        'privileged': True,
        'strategy': 'handwritten_artifact' if generated(arm) else 'true_label',
    }
    dump(directory / 'reference.json', marker)
    try:
        filename = artifact_name(arm)
        if generated(arm):
            code = source_for(task_id, arm, root)
            (output / filename).write_text(code, encoding='utf-8')
        else:
            labels = strict_json(regular_file(task / 'private/labels.json', task, 16384))
            if labels != {'correct': 'PASS', 'faulty': 'FAIL'} or variant not in labels:
                raise ValueError('Reference labels are invalid')
            dump(
                output / filename,
                {
                    'verdict': labels[variant],
                    'reason': 'Privileged reference solution: true label, not a judge prediction.',
                },
            )
        data = regular_file(output / filename, output, 65536)
        (sealed / filename).write_bytes(data)
        sha = digest(data)
        dump(
            directory / 'submission.json',
            {'sha256': sha, 'sealed': True, 'present': True, 'reference': True, 'reference_version': VERSION},
        )
        dump(directory / 'reference.json', {**marker, 'artifact_sha256': sha})
        if not generated(arm):
            phase, operation = ('grading', 'grade_reference_label')
            return grade(sealed / filename, task / 'private/labels.json', variant, logs)
        phase, operation = ('setup', 'prepare_reference_images')
        if needs_reference_images(arm, code):
            capture_arm = arm.replace('_ui', '_visual')
            references = prepare_references(root, task, directory / 'preparation', capture_arm)
        else:
            from gui_agent_bench.visual import seal_references

            references = sealed / 'references'
            config = runtime(task)
            seal_references(None, references, (config['viewport_width'], config['viewport_height']))
        from gui_agent_bench.visual import reference_digest, seal_references

        if references != sealed / 'references':
            config = runtime(task)
            seal_references(references, sealed / 'references', (config['viewport_width'], config['viewport_height']))
        reference_sha = reference_digest(sealed / 'references')
        dump(
            directory / 'submission.json',
            {
                'sha256': sha,
                'sealed': True,
                'present': True,
                'references_sha256': reference_sha,
                'reference': True,
                'reference_version': VERSION,
            },
        )
        phase, operation = ('execution', 'verify_reference_pair')
        from gui_agent_bench.verifier.oracle import verify_pair

        result = verify_pair(task, sealed / filename, directory / 'verification', arm, references=sealed / 'references')
        return write_result(logs, **{k: v for k, v in result.items() if k != 'planned_trials'})
    except Exception as exc:
        return write_result(
            logs,
            status='trial_error',
            reason='Reference preparation or grading failed.',
            diagnostics=diagnostics(
                getattr(exc, 'diagnostic_issues', None)
                or [issue(exc, phase=phase, operation=operation, impact='zero_credit')]
            ),
        )


def run(root, task, arm, variant, output):
    task_id = task.relative_to(root / 'tasks').as_posix()
    import tomllib

    metadata = tomllib.loads(regular_file(task / 'task.toml', task).decode())['metadata']
    validate(task_id, arm, root)
    if generated(arm) and variant != 'pair':
        raise ValueError('Reference programs require both variants; use --variant pair')
    if variant not in {'correct', 'faulty', 'pair'}:
        raise ValueError('Unknown reference variant')
    variants = ['correct'] if generated(arm) else ['correct', 'faulty'] if variant == 'pair' else [variant]
    directory = output.resolve() / uuid.uuid4().hex[:16]
    directory.mkdir(parents=True, exist_ok=False)
    planned = [{'id': uuid.uuid4().hex[:16], 'variant': v} for v in variants]
    shared = {
        'model': MODEL,
        'reference': True,
        'reference_version': VERSION,
        'scope': SCOPE,
        'fixture': False,
        'research_core': False,
        'agent_bypassed': True,
        'action_contract': ACTION_CONTRACT,
        'failure_contract': FAILURE_VERSION,
        'environment_contract': ENVIRONMENT_VERSION,
        'environment_profile': runtime(task)['environment_profile'],
    }
    plan = {
        **shared,
        'task': task_id,
        'arm': arm,
        'platform': metadata['platform'],
        'domain': metadata.get('domain', metadata['platform']),
        'task_status': metadata['status'],
        'planned_trials': len(planned),
        'trials': planned,
    }
    if generated(arm):
        plan.update(
            planned_artifacts=1,
            planned_executions=len(planned_variants()),
            authoring_state='correct',
            abi=abi(arm, metadata['platform']),
        )
    dump(directory / 'plan.json', plan)
    for entry in planned:
        write_result(directory / 'trials' / entry['id'] / 'logs/verifier', status='planned')
    results = []
    dump(
        directory / 'summary.json',
        {**shared, **aggregate(results, len(planned), variant == 'pair'), 'status': 'running'},
    )
    for entry in planned:
        print(f"Writing privileged reference {entry['id']} ({arm}); agent bypassed", flush=True)
        result = run_trial(root, task, directory / 'trials' / entry['id'], entry['variant'], arm)
        results.append(result)
        print(f"Reference {entry['id']}: {result['status']}, reward={result['reward']}", flush=True)
        dump(
            directory / 'summary.json',
            {**shared, **aggregate(results, len(planned), variant == 'pair'), 'status': 'running'},
        )
    summary = {
        **shared,
        **aggregate(results, len(planned), variant == 'pair'),
        'status': 'complete',
        'run_directory': str(directory),
        'provider_cost_usd': 0,
    }
    if generated(arm):
        summary.update(
            planned_artifacts=1,
            planned_executions=len(planned_variants()),
            paired_score=results[0]['reward'],
            authoring_state='correct',
            abi=abi(arm, metadata['platform']),
        )
    dump(directory / 'summary.json', summary)
    print(json.dumps(summary, indent=2), flush=True)
    return summary
