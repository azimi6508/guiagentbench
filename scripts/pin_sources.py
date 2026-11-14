"""Refresh source identities after an intentional source change; grants no qualification."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_files(root=ROOT):
    files = [root / 'pyproject.toml', root / '.dockerignore']
    for directory in ('src', 'configs', 'runtime', 'scripts', 'tests'):
        for path in (root / directory).rglob('*'):
            if (
                not path.is_file()
                or path.is_symlink()
                or any(
                    part in {'__pycache__', 'node_modules', 'qualifications', 'qualification', 'data', 'build', 'dist'}
                    for part in path.parts
                )
                or any(part.endswith('.egg-info') for part in path.parts)
                or path.name == 'qualification.json'
                or path
                in {
                    root / 'runtime/codex/lock.json',
                    root / 'runtime/cursor/lock.json',
                    root / 'runtime/claude/lock.json',
                }
                # Operator-supplied Codex model catalogs stay local (see .gitignore).
                or (path.parent == root / 'configs/codex/models' and path.suffix == '.json')
                or path.suffix in {'.pyc', '.png', '.jpg', '.mp3', '.mp4', '.ogg', '.webm', '.woff2'}
            ):
                continue
            files.append(path)
    return sorted(files)


def main():
    # Parse first: --help must not rewrite the lock files.
    argparse.ArgumentParser(
        description=__doc__ + ' Rewrites the files map in runtime/{codex,cursor,claude}/lock.json.'
    ).parse_args()
    files = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files()}
    for runner in ('codex', 'cursor', 'claude'):
        path = ROOT / 'runtime' / runner / 'lock.json'
        lock = json.loads(path.read_text())
        lock['files'] = files
        path.write_text(json.dumps(lock, indent=2) + '\n')
    print('Source identities refreshed. Run local qualification before model evaluation.')


if __name__ == '__main__':
    main()
