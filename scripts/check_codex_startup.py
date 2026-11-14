#!/usr/bin/env python3
"""No-inference check. Never starts/resumes a model turn or opens a login flow."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    from gui_agent_bench.runners.registry import add_options, resolve

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model')
    parser.add_argument('--list-models', action='store_true')
    add_options(parser)
    args = parser.parse_args()
    if not args.list_models and not args.model:
        parser.error('--model is required unless --list-models is selected')
    from gui_agent_bench.runners.codex import launch, native_boundary
    from gui_agent_bench.runners.codex_auth import source_path, validate_directory
    from gui_agent_bench.runners.codex_config import validate_lock
    from gui_agent_bench.runners.base import AuthoringContext
    from gui_agent_bench.docker import docker
    from gui_agent_bench.io import digest

    containers, networks = [], []
    try:
        validate_lock(ROOT)
        native_boundary()  # precise platform diagnostic, before accessing auth
        source = source_path(args.codex_auth_dir)
        validate_directory(source, [ROOT])
        # Inventory uses a catalog-independent placeholder solely for config;
        # it never starts a thread/turn or chooses a default evaluation model.
        spec = resolve(args.model or 'codex/inventory-only', reasoning_effort=args.codex_reasoning_effort)
        with tempfile.TemporaryDirectory(prefix='gab-startup-') as folder:
            directory = Path(folder)
            for name in ['workspace', 'workspace/output', 'output', 'config', 'logs/agent']:
                (directory / name).mkdir(parents=True, exist_ok=True)
            data = b'Synthetic startup fixture. No evaluation is running.\n'
            (directory / 'workspace/instruction.md').write_bytes(data)
            manifest = {'arm': 'judge_visual', 'platform': 'web', 'files': {'instruction.md': digest(data)}}
            prefix = 'gab-' + uuid.uuid4().hex[:16]
            for suffix in ('capture', 'inference'):
                net = prefix + '-' + suffix
                networks.append(net)
                docker('network', 'create', '--internal', net)
            context = AuthoringContext(
                prefix[4:],
                'judge_visual',
                'web',
                (960, 640),
                directory / 'workspace',
                manifest,
                directory / 'output',
                directory / 'config',
                directory / 'logs/agent',
                networks[-1],
                None,
                30,
            )
            result = launch(
                ROOT, spec, context, source, containers, networks, infer=False, list_models=args.list_models
            )
            if args.list_models:
                print(json.dumps({'models': result['models'], 'inference_started': False}, indent=2))
            else:
                print(json.dumps({'status': 'passed', 'model': spec.model, 'inference_started': False}))
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(json.dumps({'status': 'unavailable', 'reason': str(exc), 'inference_started': False}))
        return 1
    finally:
        for name in reversed(containers):
            docker('rm', '-f', name, check=False)
        for name in reversed(networks):
            docker('network', 'rm', name, check=False)


if __name__ == '__main__':
    raise SystemExit(main())
