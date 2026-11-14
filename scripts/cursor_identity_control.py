"""Five independent actual-CLI identity controls, all stopped before inference."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--cursor-auth-dir', type=Path)
    parser.add_argument('--count', type=int, default=5, choices=range(1, 21))
    args = parser.parse_args()
    out = args.output.resolve()
    out.relative_to(ROOT)
    out.mkdir(parents=True, exist_ok=False)
    report = dict(schema='cursor-identity-stability-v1', status='failed', controls=[], real_inference_started=False)
    for index in range(args.count):
        child = out / f'control-{index+1:02}'
        command = [
            sys.executable,
            str(ROOT / 'scripts/cursor_container_control.py'),
            '--output',
            str(child),
            '--model',
            args.model,
            '--identity-probe',
        ]
        if args.cursor_auth_dir:
            command += ['--cursor-auth-dir', str(args.cursor_auth_dir)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=100)
        (out / f'control-{index+1:02}.log').write_text(result.stdout + result.stderr)
        value = json.loads((child / 'control.json').read_text())
        report['controls'].append(
            dict(path=str(child.relative_to(ROOT)), status=value.get('status'), identity=value.get('identity'))
        )
        (out / 'control.json').write_text(json.dumps(report, indent=2) + '\n')
        if result.returncode or value.get('status') != 'passed':
            return 1
    identities = [c['identity'] for c in report['controls']]
    binding = lambda value: {k: value[k] for k in ('model_id', 'sha256', 'schema')}
    if all(binding(value) == binding(identities[0]) for value in identities):
        report.update(
            status='passed',
            identity=binding(identities[0]),
            distinct_wire_identities=len({i['wire_sha256'] for i in identities}),
        )
    (out / 'control.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return int(report['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
