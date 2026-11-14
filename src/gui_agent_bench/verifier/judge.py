"""Strict artifact-only judge grading, also usable by external harnesses."""

import contextlib
import signal
import threading
from pathlib import Path

from gui_agent_bench.budgets import JUDGMENT_CHECK_SECONDS
from gui_agent_bench.io import digest, dump, regular_file, strict_json
from gui_agent_bench.failures import Failure, issue, diagnostics, summarize


class CheckTimeout(Exception):
    """The verdict check exceeded JUDGMENT_CHECK_SECONDS."""


@contextlib.contextmanager
def time_limit(seconds):
    """Bound the verdict check. The interval timer needs the main thread of a POSIX process."""
    if not hasattr(signal, 'setitimer') or threading.current_thread() is not threading.main_thread():
        yield
        return

    def expired(*_):
        raise CheckTimeout()

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def write_result(output: Path, *, status: str, reward: int = 0, **fields) -> dict:
    result = {'status': status, 'reward': reward, 'planned_trials': 1, **fields}
    if status != 'planned':
        result.setdefault('diagnostics', diagnostics([]))
    output.mkdir(parents=True, exist_ok=True)
    (output / 'reward.txt').write_text(f'{reward}\n', encoding='utf-8')
    dump(output / 'reward.json', {'reward': reward, 'planned_trials': 1})
    dump(output / 'metrics.json', result)
    return result


def grade(submission: Path, labels_path: Path, variant: str, output: Path) -> dict:
    """Check one verdict against its private label within the judgment-check time limit."""
    write_result(output, status='verifier_error')
    try:
        with time_limit(JUDGMENT_CHECK_SECONDS):
            return check(submission, labels_path, variant, output)
    except CheckTimeout:
        return write_result(
            output,
            status='verifier_error',
            reason='The verdict check exceeded its time limit.',
            diagnostics=diagnostics(
                [
                    issue(
                        Failure('infrastructure_error'),
                        phase='grading',
                        operation='judge_submission',
                        impact='zero_credit',
                    )
                ]
            ),
        )


def check(submission: Path, labels_path: Path, variant: str, output: Path) -> dict:
    try:
        labels = strict_json(regular_file(labels_path, labels_path.parent, 16_384))
        if labels != {'correct': 'PASS', 'faulty': 'FAIL'} or variant not in labels:
            raise ValueError('task labels or requested variant are invalid')
    except (OSError, ValueError, TypeError):
        return write_result(
            output,
            status='verifier_error',
            reason='Verifier inputs are invalid.',
            diagnostics=diagnostics(
                [
                    issue(
                        Failure('infrastructure_error'),
                        phase='grading',
                        operation='validate_labels',
                        impact='zero_credit',
                    )
                ]
            ),
        )
    try:
        data = regular_file(submission, submission.parent, 16_384)
        artifact = strict_json(data)
        if not isinstance(artifact, dict) or not {'verdict'} <= set(artifact) <= {'verdict', 'reason'}:
            raise ValueError('expected verdict and optional reason only')
        if artifact['verdict'] not in ('PASS', 'FAIL'):
            raise ValueError('verdict must be PASS or FAIL')
        if 'reason' in artifact and (not isinstance(artifact['reason'], str) or len(artifact['reason']) > 2000):
            raise ValueError('reason must be a string of at most 2000 characters')
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        return write_result(
            output,
            status='invalid_submission',
            reason='Submission is missing or malformed.',
            diagnostics=diagnostics(
                [
                    issue(
                        Failure('missing_submission' if isinstance(exc, FileNotFoundError) else 'malformed_submission'),
                        phase='sealing',
                        operation='validate_submission',
                        impact='zero_credit',
                    )
                ]
            ),
        )
    return write_result(
        output,
        status='graded',
        reward=int(artifact['verdict'] == labels[variant]),
        expected=labels[variant],
        prediction=artifact['verdict'],
        submission_sha256=digest(data),
    )


def aggregate(results: list[dict], planned: int, paired: bool) -> dict:
    successes = sum(result.get('reward', 0) == 1 and result.get('status') == 'graded' for result in results)
    return {
        'planned_trials': planned,
        'completed_trials': len(results),
        'successful_trials': successes,
        'accuracy': successes / planned if planned else 0,
        'invalid_or_missing': planned - sum(r.get('status') == 'graded' for r in results),
        'planned_pairs': int(paired),
        'paired_score': int(successes == planned and planned == 2) if paired else None,
        'failure_summary': summarize(results, planned),
    }
