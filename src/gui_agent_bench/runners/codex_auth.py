"""Host-only saved-login lifecycle. Credentials never become run evidence."""

import os
from pathlib import Path
import stat
import tempfile

from gui_agent_bench.io import strict_json

LIMIT = 1_048_576


def source_path(explicit=None):
    value = explicit or os.environ.get('GAB_CODEX_AUTH_DIR')
    if not value:
        raise ValueError('A dedicated Codex auth directory is required (--codex-auth-dir or GAB_CODEX_AUTH_DIR)')
    return Path(value).expanduser().absolute()


def validate_bytes(data):
    if len(data) > LIMIT:
        raise ValueError('Saved ChatGPT authentication exceeds its size limit')
    try:
        value = strict_json(data)
        tokens = value['tokens']
        valid = (
            isinstance(value, dict)
            and value.get('auth_mode', 'chatgpt') == 'chatgpt'
            and not value.get('OPENAI_API_KEY')
            and isinstance(tokens, dict)
            and all(isinstance(tokens.get(k), str) and tokens[k] for k in ('access_token', 'refresh_token', 'id_token'))
        )
    except (ValueError, KeyError, TypeError, UnicodeError):
        valid = False
    if not valid:
        raise ValueError('A supported saved ChatGPT login is required; API-key fallback is disabled')
    return data


def validate_directory(path, excluded=()):
    import platform

    if (
        platform.system() != 'Linux'
        or platform.machine() not in {'x86_64', 'amd64'}
        or not hasattr(os, 'getuid')
        or os.getuid() == 0
    ):
        raise ValueError('Codex requires a non-root Linux host user')
    path = Path(path).absolute()
    try:
        for parent in (path, *path.parents):
            if stat.S_ISLNK(parent.lstat().st_mode):
                raise ValueError()
        if any(path.is_relative_to(Path(p).resolve()) for p in excluded):
            raise ValueError()
        if path == Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')).absolute():
            raise ValueError()
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid():
            raise ValueError()
        fd = os.open(path / 'auth.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.getuid()
            ):
                raise ValueError()
            return validate_bytes(stream.read(LIMIT + 1))
    except (OSError, ValueError):
        raise ValueError(
            'Dedicated ChatGPT login unavailable: require an external owned 0700 directory and regular 0600 auth.json'
        ) from None


class AuthSession:
    def __init__(self, path, excluded=()):
        self.path, self.excluded = Path(path), excluded
        self.lock_fd = None
        self.temporary = None

    def __enter__(self):
        import fcntl

        data = validate_directory(self.path, self.excluded)
        try:
            self.lock_fd = os.open(self.path / '.bench.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            info = os.fstat(self.lock_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
                raise ValueError('Invalid auth lock')
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Dedicated ChatGPT login is already in use') from None
            # Re-read under lock, as native refresh can have replaced it.
            data = validate_directory(self.path, self.excluded)
            self.temporary = tempfile.TemporaryDirectory(prefix='gab-auth-')
            self.staged = Path(self.temporary.name) / 'auth.json'
            fd = os.open(self.staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def persist(self, data):
        validate_bytes(data)
        validate_directory(self.path, self.excluded)
        fd, name = tempfile.mkstemp(prefix='.auth-', dir=self.path)
        try:
            with os.fdopen(fd, 'wb') as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path / 'auth.json')
            fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            Path(name).unlink(missing_ok=True)

    def __exit__(self, *_):
        if self.temporary:
            self.temporary.cleanup()
            self.temporary = None
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None
