"""Small, dependency-free helpers used on the trusted controller side."""

import contextlib
import contextvars
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat

_moved_evidence = contextvars.ContextVar('moved_evidence', default=False)


@contextlib.contextmanager
def recorded_evidence():
    """Audit evidence that may have been moved or cloned since it was recorded.

    Container inspections keep the absolute host paths of their bind mounts.
    Inside this block a recorded path also matches its evidence file when both
    end in the same path below the evidence tree. Checks made while a trial is
    running stay outside the block and require the exact host path.
    """
    token = _moved_evidence.set(True)
    try:
        yield
    finally:
        _moved_evidence.reset(token)


def same_source(recorded, expected) -> bool:
    """Whether a recorded bind-mount source is the expected evidence path."""
    expected = Path(expected).resolve()
    if Path(recorded).resolve() == expected:
        return True
    if not _moved_evidence.get():
        return False
    root = None
    for parent in expected.parents:  # topmost ancestor holding a run or plan record
        if (parent / 'run.json').is_file() or (parent / 'plan.json').is_file():
            root = parent
    if root is None:
        return False
    tail = expected.relative_to(root).parts
    parts = PurePosixPath(recorded).parts
    return 0 < len(tail) < len(parts) and parts[-len(tail) :] == tail


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def regular_file(path: Path, root: Path, limit: int = 4_000_000) -> bytes:
    """Reject links, Windows junctions, escapes and oversized files before copying."""
    path = path.absolute()
    root = root.absolute()
    path.relative_to(root)
    cursor = path
    while True:
        info = cursor.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('links and reparse points are not admitted')
        if cursor == root:
            break
        cursor = cursor.parent
    path.resolve().relative_to(root.resolve())
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('not a regular file or exceeds the explicit byte budget')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('file exceeds the explicit byte budget')
    return data


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strict_json(data: bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    return json.loads(data.decode('utf-8'), object_pairs_hook=unique)
