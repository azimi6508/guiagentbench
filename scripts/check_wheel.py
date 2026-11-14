"""Check built distributions against source files and required license notices."""

import argparse
from pathlib import Path
import sys
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def check(wheel, root=ROOT):
    errors = []
    source = root / 'src'
    expected = [
        p
        for p in (source / 'gui_agent_bench').rglob('*')
        if p.is_file()
        and '__pycache__' not in p.parts
        and (p.suffix == '.py' or p.is_relative_to(source / 'gui_agent_bench/viewer/static'))
    ]
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            errors.append('Wheel contains duplicate file names')
        for path in expected:
            name = path.relative_to(source).as_posix()
            if name not in names:
                errors.append('Missing packaged file: ' + name)
            elif archive.getinfo(name).file_size != path.stat().st_size or archive.read(name) != path.read_bytes():
                errors.append('Packaged file differs: ' + name)
        project = tomllib.loads((root / 'pyproject.toml').read_text())['project']
        directory = project['name'].replace('-', '_') + '-' + project['version'] + '.dist-info/licenses/'
        for filename in project['license-files']:
            name = directory + filename
            if name not in names or archive.read(name) != (root / filename).read_bytes():
                errors.append('Missing or changed license notice: ' + filename)
    return errors, len(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    args = parser.parse_args()
    try:
        errors, count = check(args.wheel)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print('Could not inspect wheel: ' + str(error), file=sys.stderr)
        return 1
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print(f'Wheel checks passed: {count} package files and required license notices match.')
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
