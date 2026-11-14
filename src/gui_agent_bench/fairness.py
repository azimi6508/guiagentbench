"""Source-, task-, image- and evidence-bound local framework qualification."""

import json

from gui_agent_bench.io import digest, regular_file

VERSION = 'framework-qualification-v2'
# Kept as a convenience listing; admission and certificate lookup are task-local.
from gui_agent_bench.task_package import discover, ROOT, task_path

TASKS = discover(ROOT)


def certificate_path(root, task_id):
    from gui_agent_bench.task_package import IDENTIFIER

    if not isinstance(task_id, str) or not IDENTIFIER.fullmatch(task_id):
        raise ValueError('Invalid task identifier')
    return root / 'runtime/qualification' / (digest(task_id.encode()) + '.json')


def task_binding(root, task_id):
    task = root / 'tasks' / task_id
    files = {
        p.relative_to(task).as_posix(): digest(regular_file(p, task))
        for p in sorted(task.rglob('*'))
        if (p.is_file() or p.is_symlink()) and '__pycache__' not in p.parts
    }
    return digest(json.dumps(files, sort_keys=True).encode())


def evidence_tree(root, directory):
    """Bind every retained proof file, including frames, source and raw logs."""
    directory = directory.absolute()
    directory.relative_to(root.absolute())
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Missing or linked fairness evidence directory')
    files, size = {}, 0
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('Linked fairness evidence is not admitted')
        if path.is_dir():
            continue
        data = regular_file(path, root, 32_000_000)
        files[path.relative_to(directory).as_posix()] = digest(data)
        size += len(data)
    if not files:
        raise ValueError('Empty fairness evidence directory')
    return dict(sha256=digest(json.dumps(files, sort_keys=True).encode()), files=len(files), bytes=size)


def runtime_binding(root, tasks=None):
    from gui_agent_bench.runners.codex_config import validate_lock
    from gui_agent_bench.docker import docker, AGENT_IMAGE, WORKER_IMAGE, ORACLE_IMAGE, ORACLE_BROWSER_IMAGE
    from gui_agent_bench.task_runtime import runtime

    validate_lock(root)
    names = {AGENT_IMAGE, WORKER_IMAGE, ORACLE_IMAGE, ORACLE_BROWSER_IMAGE}
    names.update(runtime(root / 'tasks' / task)['app_image'] for task in (discover(root) if tasks is None else tasks))
    images = {image: docker('image', 'inspect', image, '--format', '{{.Id}}').strip() for image in sorted(names)}
    return dict(source_lock_sha256=digest(regular_file(root / 'runtime/codex/lock.json', root)), images=images)


def require(root, task_id):
    task_path(root, task_id)
    path = certificate_path(root, task_id)
    certificate = json.loads(regular_file(path, root, 2_000_000))
    if (
        certificate.get('schema') != VERSION
        or certificate.get('status') != 'passed'
        or certificate.get('task') != task_id
        or certificate.get('runtime') != runtime_binding(root, [task_id])
        or certificate.get('task_sha256') != task_binding(root, task_id)
    ):
        raise ValueError('Missing or stale task qualification; run qualify_framework.py --task ' + task_id)
    for name, sha in certificate['evidence'].items():
        if digest(regular_file(root / name, root, 32_000_000)) != sha:
            raise ValueError('Qualification evidence changed')
    if not certificate.get('evidence_trees'):
        raise ValueError('Qualification lacks complete evidence binding')
    for name, expected in certificate['evidence_trees'].items():
        if evidence_tree(root, root / name) != expected:
            raise ValueError('Qualification evidence tree changed')
    return certificate


def attribution(reward, issues, *, qualified):
    """Conservative reporting beside unchanged rewards, never denominator repair.

    An assertion labelled precondition by submitted code is model-authored; only
    trusted setup/transport diagnostics can establish an environment interruption.
    Unknown framework/evidence failures withhold attribution rather than guessing.
    """
    if not qualified:
        return 'unqualified_configuration'
    if reward == 1:
        return 'success'
    uncertain = {
        'capability_unavailable',
        'unknown_operation_error',
        'incomplete_trajectory',
        'legacy_ambiguous_denial',
        'evidence_overflow',
        'target_unavailable',
        'action_timeout',
        'app_scope_lost',
        'target_ambiguous',
    }
    if any(i.get('cause') in uncertain for i in issues):
        return 'requires_framework_review'
    external = {'provider_timeout', 'provider_rate_limit', 'provider_error', 'provider_transport_error'}
    if any(
        i.get('cause') in external
        or i.get('cause')
        in {'infrastructure_error', 'app_not_ready', 'reset_failure', 'device_unavailable', 'simulator_ambiguity'}
        for i in issues
    ):
        return 'environment_or_service_failure'
    from gui_agent_bench.failures import MODEL_CAUSES

    if issues and all(i.get('cause') in MODEL_CAUSES for i in issues):
        return 'model_failure'
    # A qualified, normally graded wrong prediction need not have diagnostics.
    return 'model_failure' if not issues else 'requires_framework_review'
