#!/usr/bin/env python3
"""Qualify actual-client boundaries and optionally attest saved-login startup.

Each control runs once. Provider responses are synthetic; no paid model turn
is started. A boundary certificate enables model evaluation on the selected platforms.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    from gui_agent_bench.arms import ARM_IDS
    from gui_agent_bench.runners.codex_config import validate_lock, model_catalog, qualification_path
    from gui_agent_bench.runners.codex_security import policy
    from gui_agent_bench.runners.registry import fingerprint, resolve

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fixture-model', default='gpt-5.4')
    parser.add_argument('--fixture-model-catalog', type=Path)
    parser.add_argument(
        '--native-extended',
        '--native_extended',
        dest='native_extended',
        action='store_true',
        help='Also qualify the distinct Extended native tool profile',
    )
    parser.add_argument('--codex-auth-dir', type=Path)
    parser.add_argument(
        '--reasoning-effort',
        choices=['low', 'medium', 'high', 'xhigh'],
        default='medium',
        help='Exact Codex effort to qualify; certificates are not reused across efforts',
    )
    parser.add_argument(
        '--platforms',
        nargs='+',
        choices=['web', 'mobile', 'tv'],
        default=['web'],
        help='Platforms to enable after boundary qualification',
    )
    parser.add_argument(
        '--install-boundary-certificate',
        action='store_true',
        help='After all controls and saved-login checks pass, enable the selected platforms',
    )
    args = parser.parse_args()
    if args.native_extended and 'mobile' not in args.platforms:
        parser.error('--native-extended requires --platforms to include mobile')
    if args.install_boundary_certificate and (
        model_catalog(ROOT, args.fixture_model) is None or args.fixture_model_catalog or not args.codex_auth_dir
    ):
        parser.error('Certificate requires a local model catalog in configs/codex/models and a dedicated saved login')
    effort = args.reasoning_effort
    fixture_args = ['--model', args.fixture_model, '--reasoning-effort', effort]
    if args.fixture_model_catalog:
        fixture_args += ['--model-catalog', str(args.fixture_model_catalog.resolve())]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    lock = validate_lock(ROOT)
    report = dict(
        schema='codex-qualification-v1',
        status='incomplete',
        runtime_lock_sha256=fingerprint(lock),
        container_policy=policy(ROOT),
        approved_nested_sandbox_exception=True,
        real_inference_started=False,
        fixture_model=args.fixture_model,
        reasoning_effort=effort,
        qualified_profiles=[],
        controls=[],
        scope='Credential-free client/boundary controls; GUI catalogs use synthetic stand-ins.',
        pending_gates=[
            'Selected live model must expose exactly the admitted catalog with actual account metadata.',
            'Dedicated saved-login startup, native auth refresh/export and six-arm subscription smoke.',
        ],
    )

    def save():
        (output / 'qualification.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(name, script, arguments, result_path=None, environment=None):
        command = [sys.executable, str(ROOT / 'scripts' / script), *map(str, arguments)]
        item = dict(name=name, command=command, status='failed')
        report['controls'].append(item)
        save()
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=120, cwd=ROOT, env=environment)
            (output / (name + '.log')).write_text(result.stdout + result.stderr)
            item['returncode'] = result.returncode
            data = json.loads(result_path.read_text() if result_path else result.stdout)
            item['status'] = 'passed' if result.returncode == 0 and data['status'] == 'passed' else 'failed'
            item['evidence'] = str((result_path or output / (name + '.log')).relative_to(output))
            if data.get('fixture_metadata_fallback'):
                item['fixture_metadata_fallback'] = True
            if data.get('cleanup') is False:
                item['status'] = 'failed'
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            item['error'] = str(exc)
        save()
        print(name + ': ' + item['status'], flush=True)

    for name in ('native', 'network'):
        target = output / (name + '.json')
        run(name, 'codex_' + name + '_control.py', ['--output', target], target)
    run('transport', 'codex_transport_control.py', [])
    for platform in ('web', 'mobile', 'tv'):
        for arm in ARM_IDS:
            if platform == 'tv' and arm in {'oracle_ui', 'test_ui'}:
                continue
            name = platform + '-' + arm
            target = output / name
            run(
                name,
                'codex_client_control.py',
                ['--output', target, *fixture_args, '--arm', arm, '--platform', platform],
                target / 'control.json',
            )
    for scenario in (
        'resource_denial',
        'unknown_native',
        'quota_after_write',
        'compaction_veto',
        'hook_error',
        'hook_timeout',
        'malformed_stream',
        'interrupt_timeout',
        'model_reroute',
        'tool_error',
        'zero_calls',
    ):
        target = output / scenario
        run(
            scenario,
            'codex_client_control.py',
            ['--output', target, *fixture_args, '--scenario', scenario],
            target / 'control.json',
        )
    target = output / 'authoring_recovery'
    run(
        'authoring_recovery',
        'codex_client_control.py',
        [
            '--output',
            target,
            *fixture_args,
            '--arm',
            'test_visual',
            '--platform',
            'mobile',
            '--scenario',
            'authoring_recovery',
        ],
        target / 'control.json',
    )
    run('evidence', 'codex_evidence_control.py', ['--source', output / 'web-judge_visual'])
    target = output / 'target_feedback'
    run(
        'target_feedback',
        'codex_client_control.py',
        ['--output', target, *fixture_args, '--arm', 'test_ui', '--platform', 'web', '--scenario', 'target_feedback'],
        target / 'control.json',
    )
    if args.native_extended:
        standard_controls = report['controls']
        report['controls'] = []
        for arm in ARM_IDS:
            name = 'native_extended-' + arm
            target = output / name
            run(
                name,
                'codex_client_control.py',
                [
                    '--output',
                    target,
                    *fixture_args,
                    '--arm',
                    arm,
                    '--platform',
                    'mobile',
                    '--profile',
                    'native_extended',
                ],
                target / 'control.json',
            )
        target = output / 'native_extended-actions'
        run(
            'native_extended-actions',
            'codex_client_control.py',
            [
                '--output',
                target,
                *fixture_args,
                '--arm',
                'test_ui',
                '--platform',
                'mobile',
                '--profile',
                'native_extended',
                '--scenario',
                'native_extended_actions',
            ],
            target / 'control.json',
        )
        report['native_extended_controls'] = report['controls']
        report['controls'] = standard_controls
        save()
    if args.install_boundary_certificate and all(c['status'] == 'passed' for c in report['controls']):
        environment = dict(os.environ, GAB_CODEX_AUTH_DIR=str(args.codex_auth_dir.resolve()))
        # Inventory uses the ordinary upstream catalog, before the selected
        # model's restricted metadata is applied. Never log the auth path.
        result = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/check_codex_startup.py'), '--list-models'],
            capture_output=True,
            text=True,
            timeout=150,
            cwd=ROOT,
            env=environment,
        )
        inventory = json.loads(result.stdout)
        (output / 'account-inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')
        available = result.returncode == 0 and any(
            m['model'] == args.fixture_model and effort in m['supportedReasoningEfforts']
            for m in inventory.get('models', [])
        )
        report['controls'].append(dict(name='account_inventory', status='passed' if available else 'failed'))
        if available:
            run(
                'saved_login_startup',
                'check_codex_startup.py',
                ['--model', 'codex/' + args.fixture_model, '--codex-reasoning-effort', effort],
                environment=environment,
            )
        if all(
            c['status'] == 'passed' and not c.get('fixture_metadata_fallback')
            for c in report['controls'] + report.get('native_extended_controls', [])
        ):
            from gui_agent_bench.runners.codex import image_ids

            if fingerprint(validate_lock(ROOT)) != report['runtime_lock_sha256']:
                raise ValueError('Runtime sources changed during qualification')
            report.update(
                status='passed',
                stage='boundary-qualified',
                images=image_ids(),
                qualified_profiles=[
                    [args.fixture_model, effort, arm, platform]
                    for platform in dict.fromkeys(args.platforms)
                    for arm in ARM_IDS
                    if platform != 'tv' or arm not in {'oracle_ui', 'test_ui'}
                ],
                pending_gates=['First-attempt live platform smoke and paired environment audits.'],
            )
            if args.native_extended:
                report['qualified_environment_profiles'] = [
                    [args.fixture_model, effort, arm, 'mobile', 'native_extended'] for arm in ARM_IDS
                ]
            save()
            certificate = qualification_path(ROOT, resolve('codex/' + args.fixture_model, reasoning_effort=effort))
            certificate.parent.mkdir(parents=True, exist_ok=True)
            temporary = certificate.with_suffix('.tmp')
            temporary.write_text(json.dumps(report, indent=2) + '\n')
            temporary.replace(certificate)
            print('Boundary qualification passed; selected platforms enabled.', flush=True)
            return 0
    report['status'] = (
        'blocked'
        if any(c['status'] != 'passed' for c in report['controls'] + report.get('native_extended_controls', []))
        else 'incomplete'
    )
    save()
    print('Live qualification: ' + report['status'] + ' (see pending_gates)', flush=True)
    return 1  # A local fixture is never a passing live-model certificate.


if __name__ == '__main__':
    raise SystemExit(main())
