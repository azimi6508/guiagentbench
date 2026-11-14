"""Fixed PID-1 supervisor; host-only auth export is separate from protocol stdout."""

import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

CONTROL = Path('/run/control')
AUTH = Path('/run/codex/auth.json')


def main():
    mode = sys.argv[1:]
    if mode == ['export-auth']:
        fd = os.open(AUTH, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            data = stream.read(1_048_577)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or len(data) > 1_048_576:
                raise ValueError()
            sys.stdout.buffer.write(data)
        return
    if mode == ['shutdown']:
        (CONTROL / 'shutdown').touch()
        return
    if mode == ['watch-child']:
        while not (CONTROL / 'child.json').exists():
            time.sleep(0.1)
        print((CONTROL / 'child.json').read_text())
        return
    if mode:
        raise ValueError()
    os.umask(0o077)
    AUTH.write_bytes(Path('/auth-input/auth.json').read_bytes())
    AUTH.chmod(0o600)
    Path('/run/codex/config.toml').symlink_to('/config/config.toml')
    child = subprocess.Popen(
        ['/opt/codex/bin/codex', 'app-server', '--listen', 'stdio://', '--strict-config'], close_fds=True
    )
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while child.poll() is None and not stopping and not (CONTROL / 'shutdown').exists():
        time.sleep(0.1)
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    (CONTROL / 'child.json').write_text(json.dumps({'exit_code': child.returncode}))
    deadline = time.monotonic() + 30
    while not stopping and not (CONTROL / 'shutdown').exists() and time.monotonic() < deadline:
        time.sleep(0.1)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        sys.stderr.write('Codex runtime control failed.\n')
        sys.exit(1)
