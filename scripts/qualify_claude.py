"""Qualify the pinned Claude Code boundary before a separately recorded model smoke.

The actual CLI runs in its production image through the production gateway,
which relays to a credential-free scripted upstream. GUI catalogs and image
observations are synthetic; they do not qualify real native devices or
establish model accuracy. With --model, one GET /v1/models request resolves
the selected model's identity with the selected credential; no inference starts.
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
    from gui_agent_bench.io import dump, digest, regular_file
    from gui_agent_bench.runners.registry import resolve, fingerprint
    from gui_agent_bench.runners.claude_config import validate_lock, qualification_path, EFFORTS
    from gui_agent_bench.runners.claude import image_ids, identity_probe

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', help='Explicit Anthropic model ID, for example claude-sonnet-5-5')
    parser.add_argument('--effort', choices=EFFORTS, default='medium')
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
        help='Also qualify the Extended native catalog',
    )
    parser.add_argument('--install-boundary-certificate', action='store_true')
    args = parser.parse_args()
    if args.native_extended and 'mobile' not in args.platforms:
        parser.error('--native-extended requires mobile platform')
    if args.install_boundary_certificate and not args.model:
        parser.error('Installing requires --model')
    agent = resolve('claude/' + args.model, reasoning_effort=args.effort) if args.model else None
    output = args.output.resolve()
    output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    lock = fingerprint(validate_lock(ROOT))
    images = image_ids()
    report = dict(
        schema='claude-qualification-v1',
        status='incomplete',
        runtime_lock_sha256=lock,
        images=images,
        real_inference_started=False,
        controls=[],
        qualified_profiles=[],
        pending_gates=[
            'Separately recorded first-attempt web smoke with the selected model.',
            'Real mobile/TV execution and relay audits before native runtime claims.',
        ],
    )

    def save():
        dump(output / 'qualification.json', report)

    def control(name, *extra, timeout=300):
        item = {'name': name, 'status': 'failed'}
        report['controls'].append(item)
        save()
        command = [
            sys.executable,
            str(ROOT / 'scripts/claude_client_control.py'),
            '--output',
            str(output / name),
            *extra,
        ]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        (output / (name + '.log')).write_text(result.stdout + result.stderr)
        path = output / name / 'control.json'
        if result.returncode == 0 and path.exists() and json.loads(path.read_text()).get('status') == 'passed':
            item['status'] = 'passed'
        save()
        print(name + ': ' + item['status'], flush=True)

    item = {'name': 'security-tests', 'status': 'failed'}
    report['controls'].append(item)
    # Test this tree's sources, never an installed gui_agent_bench elsewhere on the path.
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(ROOT / 'src'), os.environ.get('PYTHONPATH')])))
    result = subprocess.run(
        [sys.executable, '-m', 'unittest', 'tests.test_claude_runner', '-v'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    (output / 'security-tests.log').write_text(result.stdout + result.stderr)
    item['status'] = 'passed' if result.returncode == 0 else 'failed'
    print('security-tests: ' + item['status'], flush=True)
    for platform in ('web', 'mobile', 'tv'):
        for arm in ARM_IDS:
            if platform == 'tv' and arm.endswith('_ui'):
                continue
            control(platform + '-' + arm, '--arm', arm, '--platform', platform)
    if args.native_extended:
        for arm in ARM_IDS:
            control('native_extended-' + arm, '--arm', arm, '--platform', 'mobile', '--profile', 'native_extended')
    control('zero-calls', '--mode', 'zero_calls')
    control('subscription-shape', '--auth-kind', 'oauth', '--arm', 'test_ui', '--platform', 'web')
    control('native-tool-refused', '--mode', 'native_tool')
    control('rate-limit-not-replayed', '--mode', 'rate_limit')
    if any(c['status'] != 'passed' for c in report['controls']):
        report['status'] = 'blocked'
        save()
        return 1
    report['status'] = 'boundary_controls_passed'
    if agent:
        try:
            identity = identity_probe(ROOT, agent)
            dump(output / 'model-identity.json', identity)
            if identity.get('id') != agent.model:
                raise ValueError('The selected model ID resolves to a different catalog ID; select the exact ID')
            report.update(
                model_identity_sha256=identity['sha256'],
                model_identity_schema=identity['schema'],
                resolved_model_id=identity['id'],
            )
        except Exception as exc:
            from gui_agent_bench.failures import issue

            report.update(
                status='blocked',
                account_failure=issue(exc, phase='setup', operation='claude_model_identity', impact='zero_credit'),
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
            agent_spec=agent.record(),
            qualified_profiles=[
                [agent.model, arm, platform, 'generic']
                for platform in dict.fromkeys(args.platforms)
                for arm in ARM_IDS
                if platform != 'tv' or not arm.endswith('_ui')
            ]
            + ([[agent.model, arm, 'mobile', 'native_extended'] for arm in ARM_IDS] if args.native_extended else []),
        )
        report['evidence'] = {
            p.relative_to(ROOT).as_posix(): digest(regular_file(p, ROOT, 64_000_000))
            for p in sorted(output.rglob('*'))
            if p.is_file() and p.name != 'qualification.json'
        }
        dump(qualification_path(ROOT, agent), report)
        from gui_agent_bench.task_package import discover

        web_tasks = [task for task in discover(ROOT) if task.startswith('web/')]
        if web_tasks:
            dump(
                output / 'web-smoke-plan.json',
                dict(
                    schema='run-plan-v1',
                    name='Claude Code selected-model web smoke',
                    models=[agent.identifier],
                    tasks=[dict(task=web_tasks[0], arms=list(ARM_IDS), repeats=1)],
                ),
            )
    save()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
