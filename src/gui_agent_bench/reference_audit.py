"""Replay privileged reference artifacts and execution boundaries, not agent claims."""

import json
from pathlib import Path
from gui_agent_bench.arms import artifact_name, generated, ARM_IDS
from gui_agent_bench.audit import audit_broker
from gui_agent_bench.io import digest, regular_file, same_source
from gui_agent_bench.reference import MODEL, VERSION, SCOPE


def valid_preparer_mounts(helper, folder):
    binds = [m for m in helper['Mounts'] if m['Type'] != 'tmpfs']
    return (
        len(binds) == 1
        and binds[0]['Type'] == 'bind'
        and not binds[0]['RW']
        and binds[0]['Destination'] == '/control.json'
        and same_source(binds[0]['Source'], folder / 'control.json')
        and helper['Config']['Cmd'][-2:] == ['--control-file', '/control.json']
    )


def audit_reference(directory, require_probes=False):
    if require_probes:
        raise ValueError('Reference runs bypass the agent; agent forbidden-access probes require fixture/scripted')
    read = lambda root, name: json.loads(regular_file(root / name, root))
    plan = read(directory, 'plan.json')
    if (
        plan.get('model') != MODEL
        or plan.get('reference') is not True
        or plan.get('reference_version') != VERSION
        or (plan.get('research_core') is not False)
        or (plan.get('agent_bypassed') is not True)
        or (plan.get('fixture') is not False)
        or (plan.get('scope') != SCOPE)
        or (plan.get('arm') not in ARM_IDS)
        or (plan.get('planned_trials') != len(plan.get('trials', [])))
        or (not plan['trials'])
    ):
        raise ValueError('Invalid privileged reference plan')
    if plan.get('platform', plan['task'].split('/')[0]) == 'tv' and plan['arm'] not in {
        'judge_visual',
        'judge_test',
        'oracle_visual',
        'test_visual',
    }:
        raise ValueError('Reference plan enables an unavailable TV arm')
    variants = [t.get('variant') for t in plan['trials']]
    if (
        generated(plan['arm'])
        and variants != ['correct']
        or (not generated(plan['arm']) and variants not in (['correct'], ['faulty'], ['correct', 'faulty']))
    ):
        raise ValueError('Reference trial variants/denominator differ')
    reports = []
    for trial in plan['trials']:
        if len(trial['id']) != 16 or any((c not in '0123456789abcdef' for c in trial['id'])):
            raise ValueError('Invalid reference trial ID')
        root = directory / 'trials' / trial['id']
        marker, metrics = (read(root, 'reference.json'), read(root, 'logs/verifier/metrics.json'))
        if (
            marker.get('version') != VERSION
            or marker.get('model') != MODEL
            or marker.get('scope') != SCOPE
            or (marker.get('privileged') is not True)
            or (marker.get('agent_started') is not False)
            or (marker.get('provider_started') is not False)
        ):
            raise ValueError('Reference bypass identity differs')
        for name in (
            'agent-container.json',
            'effective-config.json',
            'config',
            'logs/agent',
            'logs/provider.ndjson',
            'workspace',
        ):
            if (root / name).exists():
                raise ValueError('A reference run must not claim evaluated agent artifacts')
        if metrics['status'] != 'graded':
            raise ValueError('Reference trial did not complete grading; no runtime qualification')
        filename = artifact_name(plan['arm'])
        source = regular_file(root / 'output' / filename, root, 65536)
        sealed = regular_file(root / 'sealed' / filename, root, 65536)
        submission = read(root, 'submission.json')
        sha = digest(sealed)
        if (
            source != sealed
            or submission.get('sha256') != sha
            or marker.get('artifact_sha256') != sha
            or (submission.get('reference') is not True)
            or (submission.get('present') is not True)
            or (submission.get('reference_version') != VERSION)
        ):
            raise ValueError('Directly written reference artifact changed')
        report = {
            'trial_id': trial['id'],
            'agent_bypassed': True,
            'privileged': True,
            'agent_boundary_verified': False,
            'execution_boundary_verified': False,
        }
        if not generated(plan['arm']):
            artifact = json.loads(sealed)
            expected = {'correct': 'PASS', 'faulty': 'FAIL'}.get(trial['variant'])
            if (
                marker.get('strategy') != 'true_label'
                or artifact.get('verdict') != expected
                or metrics.get('prediction') != expected
                or (metrics.get('expected') != expected)
                or (metrics.get('submission_sha256') != sha)
                or (metrics.get('reward') != 1)
            ):
                raise ValueError('Reference label grading differs from its sealed artifact')
            if any(((root / name).exists() for name in ('preparation', 'verification', 'app-container.json'))):
                raise ValueError('Reference judge must bypass app interaction and generated execution')
            report['label_grading_verified'] = True
        else:
            from gui_agent_bench.visual import reference_digest, read_references, audit_images
            from gui_agent_bench.verifier.oracle import audit_execution, audit_oracle_broker, classify, pair_result
            from gui_agent_bench.budgets import planned_variants

            if marker.get('strategy') != 'handwritten_artifact':
                raise ValueError('Wrong reference artifact strategy')
            pair = root / 'verification'
            pair_plan = read(pair, 'plan.json')
            references = pair / 'sealed/references'
            reference_sha = reference_digest(references)
            manifest, _ = read_references(references)
            if (
                submission.get('references_sha256') != reference_sha
                or pair_plan.get('references_sha256') != reference_sha
                or reference_digest(root / 'sealed/references') != reference_sha
                or (digest(regular_file(pair / 'sealed' / filename, pair, 65536)) != sha)
                or (pair_plan.get('sha256') != sha)
                or (pair_plan.get('planned_executions') != len(planned_variants()))
                or ([e['variant'] for e in pair_plan.get('executions', [])] != planned_variants())
            ):
                raise ValueError('Paired reference artifacts/denominator changed')
            preparation = root / 'preparation'
            if plan['arm'].endswith('_visual') or manifest['references']:
                capture_arm = plan['arm'].replace('_ui', '_visual')
                captured = [
                    json.loads(line) for line in regular_file(preparation / 'browser.log', preparation).splitlines()
                ]
                captures = [r['reference'] for r in captured if 'reference' in r]
                if (
                    len(captures) != len(manifest['references'])
                    or not captures
                    or {r['name']: {'file': r['file'], 'sha256': r['sha256']} for r in captures}
                    != manifest['references']
                    or (reference_digest(preparation / 'references') != reference_sha)
                ):
                    raise ValueError('Visual references lack pre-grading public observation provenance')
                audit_oracle_broker(read(preparation, 'broker-container.json'), capture_arm, 'author')
                helper = read(preparation, 'preparer-container.json')
                networks = list(helper['NetworkSettings']['Networks'])
                if (
                    len(networks) != 1
                    or not networks[0].startswith('gab-reference-')
                    or (not networks[0].endswith('-inference'))
                ):
                    raise ValueError('Reference preparation helper network differs')
                audit_broker(
                    read(preparation, 'broker-container.json'),
                    networks[0],
                    networks[0].removesuffix('-inference') + '-capture',
                    preparation / 'setup/source.py' if plan['arm'].startswith('oracle_') else None,
                )
                if (
                    helper['Config']['Cmd'][:2] != ['-m', 'gui_agent_bench.reference_capture']
                    or not valid_preparer_mounts(helper, preparation)
                    or helper['HostConfig']['Privileged']
                    or (not helper['HostConfig']['ReadonlyRootfs'])
                    or (helper['Config']['User'] != 'pwuser')
                    or any(
                        (
                            any((x in e.split('=', 1)[0].upper() for x in ('KEY', 'TOKEN', 'LABEL', 'REWARD')))
                            for e in helper['Config']['Env']
                        )
                    )
                ):
                    raise ValueError('Reference preparation helper exceeds its boundary')
            results = []
            for entry in pair_plan['executions']:
                folder = pair / 'executions' / entry['id']
                executor = read(folder, 'executor-container.json')
                network = read(folder, 'executor-network.json')
                audit_execution(executor, network, pair / 'sealed' / filename)
                full_test = plan['arm'].startswith('test_')
                audit_broker(
                    read(folder, 'broker-container.json'),
                    network['Name'],
                    network['Name'].removesuffix('-inference') + '-capture',
                    None if full_test else folder / 'setup/source.py',
                    references,
                )
                audit_oracle_broker(read(folder, 'broker-container.json'), plan['arm'], 'execute')
                if plan.get('platform', plan['task'].split('/')[0]) == 'mobile':
                    from gui_agent_bench.mobile_audit import audit_mobile

                    audit_mobile(folder)
                    if preparation.exists():
                        audit_mobile(preparation)
                elif plan.get('platform', plan['task'].split('/')[0]) == 'tv':
                    from gui_agent_bench.tv_session import audit_app

                    audit_app(folder)
                    if preparation.exists():
                        audit_app(preparation)
                elif plan.get('platform', plan['task'].split('/')[0]) == 'web':
                    from gui_agent_bench.applications import audit_app

                    audit_app(folder)
                    if preparation.exists():
                        audit_app(preparation)
                if not full_test and preparation.exists():
                    if regular_file(folder / 'setup/source.py', folder) != regular_file(
                        preparation / 'setup/source.py', preparation
                    ):
                        raise ValueError('Oracle execution and reference preparation use different setup')
                records = [json.loads(line) for line in regular_file(folder / 'browser.log', folder).splitlines()]
                audit_images(folder / 'image-assertions', records, manifest)
                saved, state, termination = (
                    read(folder, 'result.json'),
                    read(folder, 'executor-state.json'),
                    read(folder, 'termination.json'),
                )
                recovered = classify(
                    records,
                    state['ExitCode'],
                    termination['failure'],
                    full_test=full_test,
                    termination_causes=termination.get('causes'),
                )
                if (
                    state['Running']
                    or saved.get('exit_code') != state['ExitCode']
                    or saved.get('submission_sha256') != sha
                    or (saved.get('references_sha256') != reference_sha)
                    or (saved.get('outcome') != recovered['outcome'])
                    or (saved.get('diagnostics') != recovered['diagnostics'])
                ):
                    raise ValueError('Reference execution differs from retained ledger')
                results.append(recovered)
            if pair_result(results, planned_variants())['reward'] != metrics['reward']:
                raise ValueError('Reference pair reward was not earned through execution')
            report['execution_boundary_verified'] = True
        reports.append(report)
    return {
        'status': 'pass',
        'scope': SCOPE,
        'reference_version': VERSION,
        'agent_bypassed': True,
        'agent_boundary_verified': False,
        'runtime_verified': generated(plan['arm']),
        'trials': reports,
    }
