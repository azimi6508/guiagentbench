"""Host orchestration: a fixed multi-task run over the unchanged trial controller.

Every cell is reserved before execution. Cells run sequentially (including
native tasks); there are no retries or best-attempt selection.
"""

import argparse
import json
import os
from pathlib import Path
import tomllib
import uuid

from gui_agent_bench.arms import ARM_IDS
from gui_agent_bench.budgets import DEFAULT_TIMEOUT_SECONDS, check_timeout
from gui_agent_bench.failures import diagnostics, explain, issue, model_zero

CONTROL_MODELS = {'fixture/scripted', 'reference/solution'}


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def prepare(root, spec, allow_candidate=False):
    from gui_agent_bench.task_package import discover, task_path, integration, NEGATIVE_CONTROLS

    if not isinstance(spec, dict) or spec.get('schema') != 'run-plan-v1':
        raise ValueError('Expected a run-plan-v1 object')
    if set(spec) - {'schema', 'name', 'models', 'tasks'}:
        raise ValueError('Unknown run plan fields')
    models = spec.get('models')
    if not isinstance(models, list) or not models or len(set(models)) != len(models):
        raise ValueError('Provide a nonempty list of unique models')
    from gui_agent_bench.runners.registry import resolve

    for model in models:
        resolve(model)
    if not isinstance(spec.get('tasks'), list) or not spec['tasks']:
        raise ValueError('Provide at least one task')
    cells, seen = [], set()
    for task in spec['tasks']:
        if not isinstance(task, dict) or set(task) - {'task', 'arms', 'repeats', 'fixture_program'}:
            raise ValueError('Unknown task fields')
        identifier = task.get('task')
        if identifier not in discover(root) or identifier in seen:
            raise ValueError('Unknown or duplicate task')
        seen.add(identifier)
        metadata = tomllib.loads((root / 'tasks' / identifier / 'task.toml').read_text(encoding='utf-8'))['metadata']
        if metadata['status'] not in {'smoke', 'component', 'admitted', 'example'} and not (
            allow_candidate and metadata['status'] == 'candidate'
        ):
            raise ValueError(f'{identifier} requires --allow-candidate for review')
        arms = task.get('arms')
        if not isinstance(arms, list) or not arms or len(set(arms)) != len(arms):
            raise ValueError('Provide unique arms for each task')
        if any(a not in ARM_IDS or a not in metadata['eligible_arms'] for a in arms):
            raise ValueError(f'Unavailable arm for {identifier}; select only eligible arms')
        repeats = task.get('repeats', 1)
        if type(repeats) is not int or not 1 <= repeats <= 100:
            raise ValueError('Planned repeats must be between 1 and 100')
        control = task.get('fixture_program', 'auto')
        allowed = {
            'auto',
            identifier,
            metadata['task_id'],
            integration(task_path(root, identifier)).get('reference_alias'),
            *NEGATIVE_CONTROLS,
        }
        if not isinstance(control, str) or control not in allowed:
            raise ValueError('Fixture control must belong to the selected task')
        for arm in arms:
            for model in models:
                for repeat in range(1, repeats + 1):
                    cells.append(
                        {
                            'task': identifier,
                            'arm': arm,
                            'model': model,
                            'repeat': repeat,
                            'fixture_program': control,
                            'attempts': [],
                        }
                    )
    name = spec.get('name', 'Evaluation run')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Run name must be nonempty text')
    if 'reference/solution' in models and models != ['reference/solution']:
        raise ValueError('Keep privileged reference validation separate from evaluated model runs')
    return {
        'schema': 'run-v1',
        'name': name,
        'status': 'planned',
        'scope': (
            'Privileged known-solution validation; agent bypassed'
            if models == ['reference/solution']
            else 'Scripted harness checks' if models == ['fixture/scripted'] else 'Model evaluation · review scope'
        ),
        **({'reference': True, 'reference_version': 'reference-run-v1'} if models == ['reference/solution'] else {}),
        'research_core': False,
        'cells': cells,
    }


def reference_validation_failed(summary):
    """A known-solution check must earn full credit; model scores are unchanged."""
    if summary.get('reference') is not True and summary.get('model') != 'reference/solution':
        return False
    return (
        summary.get('status') != 'complete'
        or summary.get('invalid_or_missing', 0) != 0
        or summary.get('accuracy') != 1
        or summary.get('planned_pairs', 0) > 0
        and summary.get('paired_score') != 1
    )


def health(directory, summary, model=None):
    """Separate evaluation errors that need review from zero-credit model outcomes.

    Wrong answers, behavioral mismatches and invalid results explained entirely
    by the evaluated model (such as a missing submission) are results, not
    errors. Setup, controller, provider and unclassified failures are errors,
    as is any invalid result from a scripted control or reference solution.
    Never infer causes from exception text.
    """
    from gui_agent_bench.io import regular_file, strict_json

    issues = list(summary.get('preflight', {}).get('diagnostics', {}).get('issues', []))
    for path in sorted(directory.glob('trials/*/logs/verifier/metrics.json')):
        result = strict_json(regular_file(path, directory))
        issues.extend(result.get('diagnostics', {}).get('issues', []))
    zero = [i for i in issues if i.get('version') == 'failure-v1' and i.get('impact') == 'zero_credit']
    shared_causes = {
        'infrastructure_error',
        'provider_error',
        'provider_transport_error',
        'provider_rate_limit',
        'provider_timeout',
        'device_unavailable',
        'simulator_ambiguity',
    }
    blocking = [i for i in zero if i.get('phase') in {'setup', 'controller'} or i.get('cause') in shared_causes]
    control = (
        model in CONTROL_MODELS
        or summary.get('model') in CONTROL_MODELS
        or summary.get('reference') is True
        or summary.get('fixture') is True
    )
    invalid = bool(summary.get('invalid_or_missing', 0))
    outcome = invalid and not blocking and model_zero(zero, control=control)
    problems = []
    if summary.get('status') != 'complete':
        problems.append(f"The evaluation ended with status {summary.get('status')!r}.")
        problems.extend(
            c['message']
            for c in summary.get('preflight', {}).get('checks', [])
            if c.get('status') == 'failed' and c.get('message')
        )
    if reference_validation_failed(summary):
        problems.append('The reference solution did not earn full credit.')
    if blocking or (invalid and not outcome):
        problems.append(explain(zero) or 'A missing or invalid result has no recorded diagnostic.')
    shown = zero if problems or outcome else []
    return {
        'errors': bool(problems),
        'error': ' '.join(problems) or None,
        'note': explain(zero) if outcome else None,
        'diagnostics': diagnostics(shown),
    }


def score(summary):
    return summary.get('paired_score') if summary.get('planned_pairs') else summary.get('accuracy')


def result_counts(manifest):
    attempts = [c['attempts'][0] for c in manifest['cells'] if c['attempts']]
    return {
        'planned': len(manifest['cells']),
        'attempted': len(attempts),
        'finished': sum(a['status'] in {'complete', 'failed'} for a in attempts),
        'credited': sum(a.get('score') == 1 and a['status'] == 'complete' for a in attempts),
        'failed': sum(a['status'] == 'failed' for a in attempts),
        'interrupted': sum(a['status'] == 'interrupted' for a in attempts),
        'unstarted': len(manifest['cells']) - len(attempts),
    }


def describe(attempt):
    if attempt['status'] == 'failed':
        return f"ERROR, needs review (zero credit): {attempt['error']}"
    if attempt.get('score') == 1:
        return 'credited'
    return 'zero credit' + (f" (model outcome: {attempt['note']})" if attempt.get('note') else '')


def execute(
    root,
    spec,
    output,
    *,
    timeout=DEFAULT_TIMEOUT_SECONDS,
    allow_candidate=False,
    fixture_probe=False,
    runner=None,
    preflight=None,
    codex_auth_dir=None,
    codex_reasoning_effort="medium",
    cursor_auth_dir=None,
    claude_effort="medium",
    opencode_variant=None,
):
    manifest = prepare(root, spec, allow_candidate)
    check_timeout(timeout)
    if fixture_probe and any(c['model'] != 'fixture/scripted' for c in manifest['cells']):
        raise ValueError('Isolation probes require exclusively scripted models')
    from gui_agent_bench.runners.registry import spec_for, fingerprint, ACCOUNT_RUNNERS

    agents = {
        c['model']: spec_for(
            c['model'],
            codex_effort=codex_reasoning_effort,
            claude_effort=claude_effort,
            opencode_variant=opencode_variant,
        )
        for c in manifest['cells']
    }
    has_codex = any(a.runner == 'codex' for a in agents.values())
    has_cursor = any(a.runner == 'cursor' for a in agents.values())
    has_account_runner = any(a.runner in ACCOUNT_RUNNERS for a in agents.values())
    if has_account_runner:
        for cell in manifest['cells']:
            cell['agent_spec'] = agents[cell['model']].record()
    manifest.update(timeout_seconds=timeout, fixture_probe=fixture_probe, allow_candidate=allow_candidate)
    if runner is None:
        from gui_agent_bench.trial import run as runner
    folder = output.resolve() / uuid.uuid4().hex[:16]
    folder.mkdir(parents=True, exist_ok=False)
    save(folder / 'run.json', manifest)
    print(f'Run directory: {folder}', flush=True)
    try:
        from gui_agent_bench.preflight import check, print_report

        manifest['status'] = 'preflight'
        save(folder / 'run.json', manifest)
        auth_options = {}
        if preflight is None:
            if has_codex:
                auth_options['credential_source'] = codex_auth_dir
            if has_cursor:
                auth_options['cursor_credential_source'] = cursor_auth_dir
        manifest['preflight'] = (preflight or check)(root, manifest, **auth_options)
        print_report(manifest['preflight'])
        if manifest['preflight']['status'] != 'passed':
            manifest['status'] = 'preflight_failed'
            manifest['result'] = result_counts(manifest)
            save(folder / 'run.json', manifest)
            print('No evaluations started. The full plan is retained.', flush=True)
            return folder, manifest
        from gui_agent_bench.fairness import certificate_path
        from gui_agent_bench.io import digest, regular_file

        certificates = {
            c['task']: certificate_path(root, c['task']) for c in manifest['cells'] if c['model'] not in CONTROL_MODELS
        }
        if certificates:
            manifest['framework_qualification_sha256'] = {
                task: digest(regular_file(path, root)) for task, path in certificates.items() if path.is_file()
            }
        if has_account_runner:
            from importlib import import_module

            contracts = {}
            for name in ACCOUNT_RUNNERS:
                selected = [a for a in agents.values() if a.runner == name]
                if selected:
                    config = import_module('gui_agent_bench.runners.' + name + '_config')
                    backend = import_module('gui_agent_bench.runners.' + name)
                    contracts[name] = config.resolved(
                        root,
                        selected,
                        [c for c in manifest['cells'] if agents[c['model']].runner == name],
                        backend.image_ids(),
                        timeout,
                    )
            contract = (
                next(iter(contracts.values()))
                if len(contracts) == 1
                else dict(schema='resolved-plan-v1', runners=contracts)
            )
            save(folder / 'resolved-plan.json', contract)
            manifest['resolved_plan_sha256'] = fingerprint(contract)
            for cell in manifest['cells']:
                cell['configuration_sha256'] = fingerprint(cell['agent_spec'])
        for cell in manifest['cells']:
            selected = agents[cell['model']]
            if selected.runner == 'opencode' and selected.reasoning_effort:
                cell['model_variant'] = selected.reasoning_effort
        manifest['status'] = 'running'
        for i, cell in enumerate(manifest['cells']):
            relative = f'evaluations/{i:04d}/attempt-1'
            destination = folder / relative
            destination.mkdir(parents=True)
            attempt = {'path': relative, 'status': 'running'}
            cell['attempts'].append(attempt)
            save(folder / 'run.json', manifest)
            print(
                f"Evaluation {i + 1}/{len(manifest['cells'])} {cell['task']} {cell['arm']} ({cell['model']}): starting",
                flush=True,
            )
            try:
                summary = runner(
                    root,
                    cell['task'],
                    cell['arm'],
                    'pair',
                    cell['model'],
                    destination,
                    timeout,
                    'PASS',
                    fixture_probe,
                    allow_candidate,
                    cell['fixture_program'],
                    **(
                        {
                            'agent_spec': agents[cell['model']],
                            'credential_source': {'cursor': cursor_auth_dir, 'codex': codex_auth_dir}.get(
                                agents[cell['model']].runner
                            ),
                        }
                        if has_account_runner
                        else {'agent_spec': agents[cell['model']]} if cell.get('model_variant') else {}
                    ),
                )
                child = Path(summary['run_directory']).resolve()
                child.relative_to(destination.resolve())
                attempt['path'] = child.relative_to(folder).as_posix()
                if has_account_runner:
                    child_plan = json.loads((child / 'plan.json').read_text())
                    child_plan['parent_resolved_plan_sha256'] = manifest['resolved_plan_sha256']
                    child_plan['configuration_sha256'] = cell['configuration_sha256']
                    child_plan['agent_spec'] = agents[cell['model']].record()
                    child_plan['runner'] = agents[cell['model']].runner
                    save(child / 'plan.json', child_plan)
                state = health(child, summary, cell['model'])
                attempt['status'] = 'failed' if state['errors'] else 'complete'
                attempt['invalid_or_missing'] = summary.get('invalid_or_missing', 0)
                attempt['score'] = score(summary)
                if state['errors']:
                    attempt['error'] = state['error']
                elif state['note']:
                    attempt['note'] = state['note']
                if state['diagnostics']['issues']:
                    attempt['diagnostics'] = state['diagnostics']
            except Exception as exc:
                failure = issue(exc, phase='controller', operation='run_evaluation', impact='zero_credit')
                attempt.update(
                    status='failed',
                    error=f"The evaluation controller failed ({failure['cause']}: {failure['message']})",
                    diagnostics=diagnostics([failure]),
                )
            manifest['result'] = result_counts(manifest)
            save(folder / 'run.json', manifest)
            print(
                f"Evaluation {i + 1}/{len(manifest['cells'])} {cell['task']} {cell['arm']}: {describe(attempt)}",
                flush=True,
            )
        manifest['status'] = 'completed_with_errors' if result_counts(manifest)['failed'] else 'complete'
    except BaseException:
        manifest['status'] = 'interrupted'
        for cell in manifest['cells']:
            for attempt in cell['attempts']:
                if attempt['status'] == 'running':
                    attempt.update(
                        status='interrupted',
                        error='The run was interrupted before this evaluation finished; zero credit, no retry.',
                    )
        manifest['result'] = result_counts(manifest)
        save(folder / 'run.json', manifest)
        raise
    manifest['result'] = result_counts(manifest)
    save(folder / 'run.json', manifest)
    result = manifest['result']
    print(
        f"Run {manifest['status']}: {result['attempted']}/{result['planned']} evaluations attempted; "
        f"{result['credited']} credited; {result['failed']} errors need review; "
        f"{result['unstarted']} not started.",
        flush=True,
    )
    return folder, manifest


def main(argv, root):
    parser = argparse.ArgumentParser(prog='gui-agent-bench run --plan')
    from gui_agent_bench.runners.registry import add_options

    add_options(parser)
    parser.add_argument('--root', type=Path, default=root)
    parser.add_argument('command', choices=['run'])
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument('--allow-candidate', action='store_true')
    parser.add_argument('--fixture-probe', action='store_true')
    parser.add_argument(
        '--check-plan', action='store_true', help='validate and print the fixed plan without starting trials'
    )
    parser.add_argument(
        '--preflight-only', action='store_true', help='check prerequisites without creating a run or launching trials'
    )
    args = parser.parse_args(argv)
    try:
        spec = json.loads(args.plan.read_text(encoding='utf-8'))
        if args.check_plan:
            print(json.dumps(prepare(args.root.resolve(), spec, args.allow_candidate), indent=2))
            return 0
        if args.preflight_only:
            from gui_agent_bench.preflight import check, print_report

            manifest = prepare(args.root.resolve(), spec, args.allow_candidate)
            manifest['fixture_probe'] = args.fixture_probe
            from gui_agent_bench.runners.registry import spec_for

            for cell in manifest['cells']:
                cell['agent_spec'] = spec_for(
                    cell['model'],
                    codex_effort=args.codex_reasoning_effort,
                    claude_effort=args.claude_effort,
                    opencode_variant=args.opencode_variant,
                    fixture_probe=args.fixture_probe,
                ).record()
            report = check(
                args.root.resolve(),
                manifest,
                credential_source=args.codex_auth_dir,
                cursor_credential_source=args.cursor_auth_dir,
            )
            print_report(report)
            return int(report['status'] != 'passed')
        _, manifest = execute(
            args.root.resolve(),
            spec,
            args.output or args.root / 'runs',
            timeout=args.timeout,
            allow_candidate=args.allow_candidate,
            fixture_probe=args.fixture_probe,
            codex_auth_dir=args.codex_auth_dir,
            codex_reasoning_effort=args.codex_reasoning_effort,
            cursor_auth_dir=args.cursor_auth_dir,
            claude_effort=args.claude_effort,
            opencode_variant=args.opencode_variant,
        )
        return int(manifest['status'] != 'complete')
    except KeyboardInterrupt:
        print(
            'Run interrupted. The plan and the evidence recorded so far are kept; unfinished evaluations earn zero '
            'and are not retried.'
        )
        return 130
    except (OSError, ValueError, TypeError) as exc:
        print(f'Run could not start: {exc}')
        return 1
