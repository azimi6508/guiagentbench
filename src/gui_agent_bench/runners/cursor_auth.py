"""Load only a dedicated login or selected Cursor key; never expose auth in evidence."""

import json
import os
from pathlib import Path
import stat
import urllib.request

LIMIT = 65_536


def source_path(explicit=None):
    return Path(
        explicit
        or os.environ.get('GAB_CURSOR_AUTH_DIR')
        or Path.home() / '.local/share/gui-agent-bench-public-cursor-auth'
    )


def credentials(explicit=None, *, root=None):
    key = os.environ.get('CURSOR_API_KEY')
    if key:
        return {'api_key': key}
    folder = source_path(explicit).absolute()
    if root and (folder == root.absolute() or root.absolute() in folder.parents):
        raise ValueError('Cursor saved login must be outside the checkout')
    # XDG_CONFIG_HOME is the dedicated directory; CLI stores Linux auth in cursor/.
    path = folder / 'cursor/auth.json'
    for parent in (folder, folder / 'cursor'):
        info = parent.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise ValueError('Cursor login directories must be owned 0700 directories')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
            or info.st_size > LIMIT
        ):
            raise ValueError('Cursor login must be an owned regular 0600 file')
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('Cursor login too large')
    value = json.loads(data)
    token = value.get('accessToken')
    if not isinstance(token, str) or not token or any(ord(c) < 33 for c in token):
        raise ValueError('Dedicated Cursor login is missing')
    return {'access_token': token}


def access_token(explicit=None, *, root=None):
    value = credentials(explicit, root=root)
    if 'access_token' in value:
        return value['access_token']
    request = urllib.request.Request(
        'https://api2.cursor.sh/auth/exchange_user_api_key',
        b'{}',
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + value['api_key']},
    )
    # This is an authentication exchange, never a model request; no retries or key persistence.
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('Cursor authentication failed')
    result = json.loads(data)
    if not isinstance(result.get('accessToken'), str) or not result['accessToken']:
        raise ValueError('Cursor authentication failed')
    return result['accessToken']
