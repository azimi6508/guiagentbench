#!/usr/bin/env python3
"""Check combined accounting and tamper rejection against actual-client evidence."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def control(source):
    from gui_agent_bench.codex_audit import reconcile
    from gui_agent_bench.codex_bridge import catalog
    from gui_agent_bench.failures import Failure
    from gui_agent_bench.runners.codex import enforce_evidence_budget

    source_report = json.loads((source / 'control.json').read_text())
    if source_report['status'] != 'passed' or source_report['scenario'] != 'happy':
        raise ValueError('Requires a passing actual-client happy control')
    tools = catalog(source_report['arm'], source_report['platform'])
    with tempfile.TemporaryDirectory(prefix='gab-evidence-control-') as folder:
        root = Path(folder)
        for name in ('agent', 'bridge'):
            shutil.copytree(source / name, root / name)
        reconcile(root / 'agent', root / 'bridge', tools)
        sizes = {
            name: sum(p.stat().st_size for p in (root / name).rglob('*') if p.is_file()) for name in ('agent', 'bridge')
        }
        total = sum(sizes.values())
        if min(sizes.values()) <= 0 or enforce_evidence_budget(root, total) != total:
            raise ValueError('Positive exact-budget control failed')
        try:
            enforce_evidence_budget(root, max(sizes.values()))
        except Failure as exc:
            if exc.cause != 'evidence_overflow':
                raise
        else:
            raise ValueError('Individually bounded streams bypassed combined cap')
        blob = next((root / 'bridge/images').glob('*.png'))
        original = blob.read_bytes()
        blob.write_bytes(original + b'tamper')
        try:
            reconcile(root / 'agent', root / 'bridge', tools)
        except ValueError:
            pass
        else:
            raise ValueError('Tampered image evidence accepted')
        blob.write_bytes(original)
        ledger = root / 'bridge/bridge.ndjson'
        lines = ledger.read_bytes().splitlines(keepends=True)
        ledger.write_bytes(b''.join(lines[:-1]))
        try:
            reconcile(root / 'agent', root / 'bridge', tools)
        except ValueError:
            pass
        else:
            raise ValueError('Incomplete bridge ledger accepted')
    return dict(
        schema='codex-evidence-control-v1',
        status='passed',
        source=str(source),
        controls=['exact_combined_budget', 'combined_overflow', 'tampered_image', 'incomplete_ledger'],
        component_bytes=sizes,
        inference_started=False,
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(control(args.source.resolve()), indent=2))
