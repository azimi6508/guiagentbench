"""Exercise the production Cursor launch topology/catalog without model inference."""

import argparse
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    from gui_agent_bench.io import dump, digest
    from gui_agent_bench.docker import docker
    from gui_agent_bench.runners.base import AuthoringContext
    from gui_agent_bench.runners.registry import resolve
    from gui_agent_bench.runners.cursor import launch

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--cursor-auth-dir', type=Path)
    parser.add_argument('--identity-probe', action='store_true')
    parser.add_argument(
        '--live-probe', action='store_true', help='Explicit tiny paid readiness turn, outside benchmark scores'
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    for name in ('workspace/output', 'output', 'config', 'logs/agent'):
        (output / name).mkdir(parents=True, exist_ok=True)
    text = b'Catalog-only runtime control. No model inference is permitted.'
    if args.live_probe:
        text = b'Reply with the single word READY. You do not need to call any tools.'
    (output / 'workspace/instruction.md').write_bytes(text)
    manifest = {'arm': 'judge_visual', 'platform': 'web', 'files': {'instruction.md': digest(text)}}
    identity = uuid.uuid4().hex[:16]
    prefix = 'gab-' + identity
    containers = []
    networks = []
    report = {'schema': 'cursor-container-control-v1', 'status': 'failed', 'real_inference_started': False}
    try:
        for suffix in ('capture', 'inference'):
            name = prefix + '-' + suffix
            networks.append(name)
            docker('network', 'create', '--internal', name)
        context = AuthoringContext(
            identity,
            'judge_visual',
            'web',
            (800, 600),
            output / 'workspace',
            manifest,
            output / 'output',
            output / 'config',
            output / 'logs/agent',
            prefix + '-inference',
            None,
            90,
        )
        result = launch(
            ROOT,
            resolve('cursor/' + args.model),
            context,
            args.cursor_auth_dir,
            containers,
            networks,
            qualification=not args.live_probe,
            startup_only=not args.identity_probe and not args.live_probe,
            identity_probe=args.identity_probe,
        )
        if not result.get('completed'):
            raise ValueError('Startup control incomplete')
        report['status'] = 'passed'
    except Exception as exc:
        from gui_agent_bench.failures import issue

        report['failure'] = issue(exc, phase='setup', operation='cursor_container_control', impact='zero_credit')
    finally:
        for name in reversed(containers):
            docker('rm', '-f', name, check=False)
        for name in reversed(networks):
            docker('network', 'rm', name, check=False)
        if args.identity_probe:
            rows = [
                json.loads(line) for line in (output / 'logs/cursor-provider.ndjson').read_text().splitlines() if line
            ]
            identities = [r['identity'] for r in rows if r.get('outcome') == 'identity_probe']
            if len(identities) == 1 and not any(
                r.get('sent_bytes') for r in rows if str(r.get('path', '')).endswith(('/BidiAppend', '/RunSSE'))
            ):
                report.update(status='passed', identity=identities[0], expected_pre_inference_rejection=True)
                report.pop('failure', None)
        if args.live_probe:
            path = output / 'logs/cursor-provider.ndjson'
            rows = [json.loads(line) for line in path.read_text().splitlines() if line] if path.exists() else []
            report['real_inference_started'] = any(
                r.get('sent_bytes', 0) > 0 and str(r.get('path', '')).endswith('/BidiAppend') for r in rows
            )
            report['outside_benchmark_scores'] = True
        dump(output / 'control.json', report)
    print(json.dumps(report, indent=2))
    return int(report['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
