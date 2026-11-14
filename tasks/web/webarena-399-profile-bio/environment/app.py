"""Private, offline Postmill task surface. No host ports or database endpoint."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import re
import threading
import mimetypes
from pathlib import Path
import subprocess
import time
from urllib.parse import unquote, urlsplit

state_lock = threading.RLock()
PROFILE = '/user/MarvelsGrantMan136'
BIO = PROFILE + '/edit_biography'
PUBLIC = Path('/var/www/html/public')
SETTINGS = json.loads(Path('/settings.json').read_text())
if set(SETTINGS) != {'drop_biography_save'} or type(SETTINGS['drop_biography_save']) is not bool:
    raise ValueError('unexpected task settings')


def reset():
    subprocess.run(['psql', '-h', '/tmp', '-U', 'postgres', '-d', 'postmill', '-v', 'ON_ERROR_STOP=1',
        '-c', "UPDATE users SET biography='t2_5adwlxvn' WHERE username='MarvelsGrantMan136'"],
        check=True, capture_output=True, timeout=10)
    sessions = Path('/var/www/html/var/sessions')
    for child in sessions.iterdir():
        if child.is_file():
            child.unlink()


class Handler(BaseHTTPRequestHandler):
    session = None
    def log_message(self, *_):
        pass

    def reply(self, status, data=b'', content_type='text/plain'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        if self.path == '/reset' and status == 200:
            self.send_header('X-GAB-Session', type(self).session)
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.serve()

    def do_GET(self):
        self.serve()

    def serve(self):
        # Drain state-changing proxy work before reset; reject queued old sessions.
        with state_lock:
            self._serve()

    def _serve(self):
        try:
            path = unquote(urlsplit(self.path).path)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 65536 or self.headers.get('Transfer-Encoding'):
                return self.reply(413)
            if path == '/reset' and self.command == 'POST' and length == 0:
                session = self.headers.get('X-GAB-Session', '')
                if not re.fullmatch('[0-9a-f]{32}', session):
                    return self.reply(400)
                reset()
                type(self).session = session
                return self.reply(200, b'{}', 'application/json')
            if self.headers.get('X-GAB-Session') != type(self).session:
                return self.reply(409)
            if path == '/' and self.command == 'GET':
                path = PROFILE
            if path not in {PROFILE, BIO}:
                # Only public packaged assets may bypass Symfony. In particular,
                # PHP, dotfiles, app sources, private controls and SQL are absent.
                target = (PUBLIC / path.lstrip('/')).resolve()
                suffix = target.suffix.lower()
                if (self.command == 'GET' and target.is_relative_to(PUBLIC)
                        and suffix in {'.css', '.js', '.png', '.jpg', '.jpeg', '.svg', '.gif', '.ico', '.woff', '.woff2', '.ttf'}
                        and target.is_file()):
                    return self.reply(200, target.read_bytes(), mimetypes.guess_type(str(target))[0] or 'application/octet-stream')
                return self.reply(403, b'This task provides the profile and biography editor.')
            if self.command == 'POST' and path != BIO:
                return self.reply(403)
            headers = {key: value for key, value in self.headers.items()
                       if key.lower() in {'content-type', 'cookie', 'accept', 'accept-language'}}
            headers['Host'] = 'app:8000'
            connection = http.client.HTTPConnection('127.0.0.1', 8082, timeout=45)
            try:
                connection.request(self.command, path, body=self.rfile.read(length), headers=headers)
                result = connection.getresponse()
                data = result.read()
                self.send_response(result.status)
                for key, value in result.getheaders():
                    if key.lower() in {'content-type', 'set-cookie', 'location', 'content-security-policy', 'x-frame-options'}:
                        self.send_header(key, value)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            finally:
                connection.close()
        except Exception as exc:
            print(json.dumps({'runtime_error': type(exc).__name__}), flush=True)
            self.reply(503, b'Application unavailable')


def wait_for_php(process, timeout=45):
    """Do not publish /reset until the actual profile can be rendered."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Postmill PHP process exited before readiness')
        connection = http.client.HTTPConnection('127.0.0.1', 8082, timeout=3)
        try:
            connection.request('GET', PROFILE, headers={'Host': 'app:8000'})
            response = connection.getresponse()
            body = response.read(2_000_001)
            if response.status == 200 and b'MarvelsGrantMan136' in body and len(body) <= 2_000_000:
                return
        except (OSError, http.client.HTTPException):
            pass
        finally:
            connection.close()
        time.sleep(.1)
    raise TimeoutError('Postmill profile did not become ready')


def main():
    # PostgreSQL uses only a container-local Unix socket. The image's generic
    # supervisor, environment-control API and unused services are never started.
    database = subprocess.Popen(['postgres', '-D', '/usr/local/pgsql/data',
        '-c', 'unix_socket_directories=/tmp', '-c', 'listen_addresses='])
    deadline = time.monotonic() + 30
    while subprocess.run(['pg_isready', '-h', '/tmp'], capture_output=True).returncode:
        if database.poll() is not None or time.monotonic() >= deadline:
            raise RuntimeError('Postmill database did not start')
        time.sleep(.2)
    reset()
    php = subprocess.Popen(['php', '-S', '127.0.0.1:8082', '-t', str(PUBLIC), '/bench/router.php'])
    try:
        wait_for_php(php)
        ThreadingHTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
    finally:
        php.terminate()
        database.terminate()


if __name__ == '__main__':
    main()
