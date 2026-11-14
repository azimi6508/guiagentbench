"""Replay recorded boundary checks for one evaluation or for every evaluation of a plan run.

The audit reads the retained evidence (workspace manifests, container and
network records, tool ledgers) and checks it against the arm's information
barriers. It never executes a submission or changes a score. No --run means no
runtime claim.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from gui_agent_bench.audit import audit_run


def audit(directory, require_probes):
    """Audit one evaluation directory; a failed audit is a result, not an exception."""
    try:
        return 0, audit_run(directory.resolve(), require_probes)
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        return 1, {'status': 'fail', 'runtime_verified': False, 'reason': str(exc)}


def plan_evaluations(run):
    """Evaluation directories of a plan run, in planned order, with their cells."""
    manifest = json.loads((run / 'run.json').read_text(encoding='utf-8'))
    for cell in manifest.get('cells', []):
        for attempt in cell.get('attempts', []):
            folder = run / attempt.get('path', '')
            # A finished attempt records its evaluation directory; an unfinished
            # one records only the attempt folder, which may hold one evaluation.
            if (folder / 'plan.json').is_file():
                yield cell, attempt, folder
                continue
            children = [p for p in sorted(folder.glob('*')) if (p / 'plan.json').is_file()] if folder.is_dir() else []
            yield cell, attempt, (children[0] if len(children) == 1 else None)


def audit_plan(run, require_probes, record):
    results, rows = [], []
    for cell, attempt, evaluation in plan_evaluations(run):
        label = f"{cell['task']} {cell['arm']}"
        if evaluation is None:
            rows.append({'evaluation': label, 'status': 'not_audited', 'reason': 'no recorded evaluation directory'})
            continue
        code, report = audit(evaluation, require_probes)
        relative = (Path(run.name) / evaluation.relative_to(run)).as_posix()
        results.append(
            {
                'evaluation': relative,
                'task': cell['task'],
                'arm': cell['arm'],
                'model': cell['model'],
                'returncode': code,
                'stdout': json.dumps(report),
            }
        )
        rows.append(
            {
                'evaluation': label,
                'path': relative,
                'status': report.get('status'),
                **({'reason': report['reason']} if report.get('reason') else {}),
            }
        )
    passed = sum(row['status'] == 'pass' for row in rows)
    summary = {
        'status': 'pass' if rows and passed == len(rows) else 'fail',
        'scope': 'Recorded boundary audit of a plan run',
        'run': run.name,
        'evaluations': len(rows),
        'passed': passed,
        'results': rows,
    }
    if record:
        target = run / 'audits.json'
        target.write_text(
            json.dumps({'schema': 'audits-v1', 'require_probes': require_probes, 'results': results}, indent=2) + '\n',
            encoding='utf-8',
        )
        summary['recorded'] = target.name
    print(json.dumps(summary, indent=2))
    return int(summary['status'] != 'pass')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        '--run',
        type=Path,
        help='an evaluation directory (plan.json and summary.json), or a plan run directory (run.json)',
    )
    parser.add_argument(
        '--require-probes',
        action='store_true',
        help='also require the forbidden-access probe evidence of a scripted --fixture-probe run',
    )
    parser.add_argument(
        '--record',
        action='store_true',
        help='for a plan run, write the results to <run>/audits.json so the viewer shows them',
    )
    args = parser.parse_args()
    if args.run is None:
        print(
            json.dumps(
                {
                    'status': 'not_run',
                    'runtime_verified': False,
                    'reason': 'Supply --run with a completed run directory.',
                }
            )
        )
        return 2
    if not args.run.is_dir():
        print(json.dumps({'status': 'fail', 'runtime_verified': False, 'reason': f'Not a directory: {args.run}'}))
        return 1
    run = args.run.resolve()
    if (run / 'run.json').is_file() and not (run / 'plan.json').is_file():
        return audit_plan(run, args.require_probes, args.record)
    if args.record:
        parser.error('--record applies to a plan run directory')
    code, report = audit(run, args.require_probes)
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
