"""Login to the dedicated Cursor account cache or list models without inference."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
URL = 'https://downloads.cursor.com/lab/2026.10.22-27dcf5f/linux/x64/agent-cli-package.tar.gz'
SHA = '85296944e4600a83c4b764f578d1502bf9c416db200d33a593e8f3ecabfdc294'


def binary():
    archive = ROOT / '.cursor-build/agent-cli-package.tar.gz'
    package = ROOT / '.cursor-build/package'
    if not archive.is_file():
        archive.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(URL, timeout=60) as response, archive.open('xb') as output:
            while block := response.read(1_048_576):
                output.write(block)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA:
        raise ValueError('Cursor download checksum differs')
    if not (package / 'cursor-agent').is_file():
        package.mkdir(parents=True, exist_ok=False)
        with tarfile.open(archive) as bundle:
            # Vendor archive has one outer directory; safe extraction rejects
            # absolute paths, traversal and external links before installing.
            for member in bundle.getmembers():
                parts = Path(member.name).parts
                if len(parts) < 2:
                    continue
                member.name = str(Path(*parts[1:]))
                bundle.extract(member, package, filter='data')
    return package / 'cursor-agent'


def cli_environment(auth_dir):
    # Do not inherit editor settings, provider keys, proxies or personal XDG data.
    auth_dir = auth_dir.expanduser().absolute()
    auth_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if auth_dir.stat().st_mode & 0o077:
        raise ValueError('Dedicated Cursor directory must be 0700')
    config = auth_dir / 'cursor'
    config.mkdir(mode=0o700, exist_ok=True)
    return {
        'PATH': '/usr/local/bin:/usr/bin:/bin',
        'NO_OPEN_BROWSER': '1',
        'XDG_CONFIG_HOME': str(auth_dir),
        'CURSOR_CONFIG_DIR': str(config),
    }


def inventory(auth_dir):
    from gui_agent_bench.runners.cursor_auth import access_token

    env = cli_environment(auth_dir)
    env['CURSOR_AUTH_TOKEN'] = access_token(auth_dir, root=ROOT)
    folder = ROOT / '.cursor-build/bootstrap'
    folder.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(binary()), 'models'], cwd=folder, env=env, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise ValueError('Cursor account model inventory failed; check the dedicated login')
    plain = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout)
    models = []
    for line in plain.splitlines():
        match = re.match(r'^\s*(?:[-*•]\s*)?([A-Za-z0-9][A-Za-z0-9._-]*)\s+(?:[-–—]|\s)\s*(.+?)\s*$', line)
        if match and match[1].lower() not in {'available', 'current', 'model', 'models', 'tip', 'use'}:
            models.append({'model': match[1], 'display_name': match[2]})
    if not models:
        raise ValueError('Cursor inventory format is unqualified; no model was selected')
    return {
        'schema': 'cursor-account-inventory-v1',
        'status': 'passed',
        'models': models,
        'real_inference_started': False,
    }


def main():
    from gui_agent_bench.runners.cursor_auth import source_path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cursor-auth-dir', type=Path)
    parser.add_argument('--login', action='store_true')
    parser.add_argument('--list-models', action='store_true')
    args = parser.parse_args()
    auth_dir = source_path(args.cursor_auth_dir)
    try:
        if args.login:
            folder = ROOT / '.cursor-build/bootstrap'
            folder.mkdir(parents=True, exist_ok=True)
            return subprocess.run([str(binary()), 'login'], cwd=folder, env=cli_environment(auth_dir)).returncode
        print(json.dumps(inventory(auth_dir), indent=2))
        return 0
    except Exception as exc:
        from gui_agent_bench.failures import issue

        print(
            json.dumps(
                {
                    'status': 'failed',
                    'failure': issue(exc, phase='setup', operation='cursor_account_inventory', impact='zero_credit'),
                }
            )
        )
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
