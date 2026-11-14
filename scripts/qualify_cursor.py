"""Qualify the pinned Cursor boundary before a separately recorded model smoke.

The actual CLI talks to a credential-free scripted provider. GUI catalogs and
image observations are synthetic; they do not qualify real native devices or
establish model accuracy. Account inventory does not start model inference.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))


def main():
    from gui_agent_bench.arms import ARM_IDS
    from gui_agent_bench.io import dump, digest, regular_file
    from gui_agent_bench.runners.registry import resolve, fingerprint
    from gui_agent_bench.runners.cursor_config import validate_lock, qualification_path
    from gui_agent_bench.runners.cursor import image_ids

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', help='Explicit Cursor account model slug; never Auto')
    parser.add_argument('--cursor-auth-dir', type=Path)
    parser.add_argument(
        '--platforms',
        nargs='+',
        choices=['web', 'mobile', 'tv'],
        default=['web'],
        help='Platforms to enable; real environment controls remain separate',
    )
    parser.add_argument(
        '--native-extended',
        '--native_extended',
        dest='native_extended',
        action='store_true',
        help='Qualify the separate Extended native catalog and action transport',
    )
    parser.add_argument('--install-boundary-certificate', action='store_true')
    args = parser.parse_args()
    if args.native_extended and 'mobile' not in args.platforms:
        parser.error('--native-extended requires mobile platform')
    if args.install_boundary_certificate and not args.model:
        parser.error('Installing requires --model')
    agent = resolve('cursor/' + args.model) if args.model else None
    output = args.output.resolve()
    output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    lock = fingerprint(validate_lock(ROOT))
    images = image_ids()
    report = dict(
        schema='cursor-qualification-v1',
        status='incomplete',
        runtime_lock_sha256=lock,
        images=images,
        real_inference_started=False,
        controls=[],
        qualified_profiles=[],
        pending_gates=[
            'Selected account model inventory and separately recorded first-attempt web smoke.',
            'Real mobile/TV execution and relay audits before native runtime claims.',
        ],
    )

    def save():
        dump(output / 'qualification.json', report)

    def run_control(name, command, result_path=None, timeout=120):
        item = {'name': name, 'status': 'failed'}
        report['controls'].append(item)
        save()
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        (output / (name + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode == 0:
            if result_path:
                value = json.loads(result_path.read_text())
                item['status'] = 'passed' if value.get('status') == 'passed' else 'failed'
            else:
                item['status'] = 'passed'
        save()
        print(name + ': ' + item['status'], flush=True)

    run_control('security-tests', [sys.executable, '-m', 'unittest', 'tests.test_cursor_runner', '-v'])
    run_control(
        'gateway-protocol',
        [sys.executable, str(ROOT / 'scripts/cursor_gateway_control.py'), '--output', str(output / 'gateway-protocol')],
        output / 'gateway-protocol/control.json',
    )
    run_control(
        'gateway-actual-client',
        [
            sys.executable,
            str(ROOT / 'scripts/cursor_client_control.py'),
            '--output',
            str(output / 'gateway-actual-client'),
            '--gateway',
            '--arm',
            'oracle_visual',
            '--platform',
            'tv',
            '--control-delay-ms',
            '10000',
        ],
        output / 'gateway-actual-client/control.json',
        timeout=180,
    )
    for platform in ('web', 'mobile', 'tv'):
        for arm in ARM_IDS:
            if platform == 'tv' and arm.endswith('_ui'):
                continue
            name = platform + '-' + arm
            run_control(
                name,
                [
                    sys.executable,
                    str(ROOT / 'scripts/cursor_client_control.py'),
                    '--output',
                    str(output / name),
                    '--arm',
                    arm,
                    '--platform',
                    platform,
                ],
                output / name / 'control.json',
            )
    run_control(
        'zero-calls',
        [
            sys.executable,
            str(ROOT / 'scripts/cursor_client_control.py'),
            '--output',
            str(output / 'zero-calls'),
            '--zero-calls',
        ],
        output / 'zero-calls/control.json',
    )
    if args.native_extended:
        for arm in ARM_IDS:
            name = 'native_extended-' + arm
            run_control(
                name,
                [
                    sys.executable,
                    str(ROOT / 'scripts/cursor_client_control.py'),
                    '--output',
                    str(output / name),
                    '--arm',
                    arm,
                    '--platform',
                    'mobile',
                    '--profile',
                    'native_extended',
                ],
                output / name / 'control.json',
            )
        name = 'native_extended-actions'
        run_control(
            name,
            [
                sys.executable,
                str(ROOT / 'scripts/cursor_client_control.py'),
                '--output',
                str(output / name),
                '--arm',
                'test_ui',
                '--platform',
                'mobile',
                '--profile',
                'native_extended',
                '--native_extended-actions',
            ],
            output / name / 'control.json',
        )
    if any(c['status'] != 'passed' for c in report['controls']):
        report['status'] = 'blocked'
        save()
        return 1
    report['status'] = 'boundary_controls_passed'
    if agent:
        from check_cursor_startup import inventory

        try:
            from gui_agent_bench.runners.cursor_auth import source_path

            account = inventory(source_path(args.cursor_auth_dir))
            selected = [m for m in account['models'] if m['model'] == agent.model]
            if len(selected) != 1:
                raise ValueError('Requested model is unavailable')
            dump(output / 'account-inventory.json', account)
            report['account_model'] = selected[0]
            command = [
                sys.executable,
                str(ROOT / 'scripts/cursor_relay_control.py'),
                '--output',
                str(output / 'relay-startup'),
                '--model',
                agent.model,
            ]
            if args.cursor_auth_dir:
                command += ['--cursor-auth-dir', str(args.cursor_auth_dir)]
            run_control('relay-startup', command, output / 'relay-startup/control.json')
            if report['controls'][-1]['status'] != 'passed':
                report['status'] = 'blocked'
                save()
                return 1
            command = [
                sys.executable,
                str(ROOT / 'scripts/cursor_container_control.py'),
                '--output',
                str(output / 'container-startup'),
                '--model',
                agent.model,
            ]
            if args.cursor_auth_dir:
                command += ['--cursor-auth-dir', str(args.cursor_auth_dir)]
            run_control('container-startup', command, output / 'container-startup/control.json')
            if report['controls'][-1]['status'] != 'passed':
                report['status'] = 'blocked'
                save()
                return 1
            command = [
                sys.executable,
                str(ROOT / 'scripts/cursor_container_control.py'),
                '--output',
                str(output / 'model-identity'),
                '--model',
                agent.model,
                '--identity-probe',
            ]
            if args.cursor_auth_dir:
                command += ['--cursor-auth-dir', str(args.cursor_auth_dir)]
            run_control('model-identity', command, output / 'model-identity/control.json')
            if report['controls'][-1]['status'] != 'passed':
                report['status'] = 'blocked'
                save()
                return 1
            identity = json.loads((output / 'model-identity/control.json').read_text())['identity']
            report['model_identity_sha256'] = identity['sha256']
            report['model_identity_schema'] = identity['schema']
            report['resolved_model_id'] = identity['model_id']
            command = [
                sys.executable,
                str(ROOT / 'scripts/cursor_identity_control.py'),
                '--output',
                str(output / 'model-identity-stability'),
                '--model',
                agent.model,
            ]
            if args.cursor_auth_dir:
                command += ['--cursor-auth-dir', str(args.cursor_auth_dir)]
            run_control(
                'model-identity-stability', command, output / 'model-identity-stability/control.json', timeout=600
            )
            if report['controls'][-1]['status'] != 'passed' or json.loads(
                (output / 'model-identity-stability/control.json').read_text()
            ).get('identity') != {k: identity[k] for k in ('model_id', 'sha256', 'schema')}:
                report['status'] = 'blocked'
                save()
                return 1
        except Exception as exc:
            from gui_agent_bench.failures import issue

            report.update(
                status='blocked',
                account_failure=issue(exc, phase='setup', operation='cursor_account_inventory', impact='zero_credit'),
            )
            save()
            return 1
    if fingerprint(validate_lock(ROOT)) != lock or image_ids() != images:
        report.update(status='blocked', source_or_image_drift=True)
        save()
        return 1
    if args.install_boundary_certificate:
        report.update(
            status='passed',
            stage='boundary-qualified',
            qualified_profiles=[
                [agent.model, arm, platform, 'generic']
                for platform in dict.fromkeys(args.platforms)
                for arm in ARM_IDS
                if platform != 'tv' or not arm.endswith('_ui')
            ]
            + ([[agent.model, arm, 'mobile', 'native_extended'] for arm in ARM_IDS] if args.native_extended else []),
            agent_spec=agent.record(),
        )
        report['evidence'] = {
            p.relative_to(ROOT).as_posix(): digest(regular_file(p, ROOT, 64_000_000))
            for p in sorted(output.rglob('*'))
            if p.is_file() and p.name != 'qualification.json'
        }
        dump(qualification_path(ROOT, agent), report)
        # Explicit platform flags select the qualification scope.
        # Real environment execution/reference audits remain separate gates.
        from gui_agent_bench.task_package import discover

        web_tasks = [task for task in discover(ROOT) if task.startswith('web/')]
        if web_tasks:
            smoke = dict(
                schema='run-plan-v1',
                name='Cursor selected-model web smoke',
                models=[agent.identifier],
                tasks=[dict(task=web_tasks[0], arms=list(ARM_IDS), repeats=1)],
            )
            dump(output / 'web-smoke-plan.json', smoke)
    save()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
