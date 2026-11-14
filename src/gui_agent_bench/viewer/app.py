"""Read-only loopback viewer for runs, reviews and agent trajectories."""

from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, urlsplit
import webbrowser

from .evidence import EvidenceIndex, display_value
from .review import Reviewer
from .server import Handler as PinnedHandler

STATIC = Path(__file__).with_name('static')
ASSET = re.compile(r'^/(?:(js)/)?([a-z][a-z0-9-]*\.(?:js|css|svg))$')
MIME = {'.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.html': 'text/html'}


def static_file(request_path):
    """Packaged frontend assets only; no traversal, no other suffixes."""
    if request_path == '/':
        return STATIC / 'index.html'
    match = ASSET.fullmatch(request_path)
    if not match:
        return None
    path = STATIC.joinpath(*filter(None, match.groups()))
    return path if path.is_file() and path.resolve().is_relative_to(STATIC.resolve()) else None


def record(index, run_id, relative, line):
    """One original stream record, with embedded image bytes replaced by a marker."""
    for number, offset, event, error in index.records(run_id, relative):
        if number == line:
            return {'path': relative, 'line': line, 'offset': offset, 'error': error, 'record': display_value(event)}
        if number > line:
            break
    raise FileNotFoundError('Record not found')


class ViewerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root, port=8080):
        self.index = EvidenceIndex(root)
        self.reviewer = Reviewer(self.index)
        super().__init__(('127.0.0.1', port), Handler)


class Handler(PinnedHandler):
    server_version = 'GUIAgentBenchViewer/3'

    def do_GET(self):
        port = self.server.server_address[1]
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if self.headers.get('Host') not in hosts or self.headers.get('Origin') not in {
            None,
            *(f'http://{h}' for h in hosts),
        }:
            self.send({'error': 'Only same-origin loopback access is supported'}, status=403)
            return
        request = urlsplit(self.path)
        query = parse_qs(request.query)

        def arg(name, default=''):
            return query.get(name, [default])[0]

        index, reviewer = self.server.index, self.server.reviewer
        try:
            asset = None if request.path.startswith('/api/') else static_file(request.path)
            if asset is not None:
                self.send(asset.read_bytes(), MIME[asset.suffix] + '; charset=utf-8')
            elif request.path == '/api/version':
                self.send({'viewer': 'viewer-v3', 'root': index.root.name})
            elif request.path == '/api/hierarchy':
                self.send(index.hierarchy())
            elif request.path == '/api/runs':
                self.send(index.listing())
            elif request.path == '/api/run':
                self.send(index.detail(arg('id')))
            elif request.path == '/api/overview':
                self.send(reviewer.run_overview(arg('run')))
            elif request.path == '/api/evaluation':
                self.send(reviewer.evaluation(arg('id')))
            elif request.path == '/api/trajectory':
                value = reviewer.trajectory(arg('id'), arg('trial'))
                if value is None:
                    raise FileNotFoundError('No agent trajectory was recorded for this trial')
                self.send(value)
            elif request.path == '/api/record':
                self.send(record(index, arg('id'), arg('path'), int(arg('line'))))
            elif request.path == '/api/events':
                offset, limit = int(arg('offset', '0')), int(arg('limit', '60'))
                if offset < 0 or not 1 <= limit <= 100:
                    raise ValueError('Invalid page')
                self.send(index.events(arg('id'), arg('path'), offset, limit))
            elif request.path == '/api/image':
                mime, data = index.embedded_image(arg('id'), arg('path'), int(arg('line')), arg('sha'))
                self.send(data, mime)
            elif request.path == '/api/artifact':
                path = index.artifact(arg('id'), arg('path'))
                self.send(path.read_bytes(), 'image/png' if path.suffix == '.png' else 'text/plain; charset=utf-8')
            else:
                self.send({'error': 'Not found'}, status=404)
        except FileNotFoundError as error:
            message = error.args[0] if error.args and isinstance(error.args[0], str) and not error.filename else None
            self.send({'error': message or 'Evidence not recorded yet or missing'}, status=404)
        except (ValueError, UnicodeError):
            self.send({'error': 'Invalid request or unreadable evidence'}, status=400)
        except OSError:
            self.send({'error': 'Evidence is temporarily unavailable'}, status=409)
        except (TypeError, AttributeError, KeyError, RecursionError):
            self.send(
                {'error': 'This record has an unsupported or malformed structure; original evidence is retained'},
                status=422,
            )


def serve(root: Path, port=8080, *, open_browser=True):
    if not 0 <= port <= 65535:
        raise ValueError('Port must be between 0 and 65535')
    server = ViewerServer(root, port)
    url = f'http://127.0.0.1:{server.server_address[1]}'
    print(f'GUIAgentBench viewer: {url}\nReading {server.index.root}\nPress Ctrl+C to stop.', flush=True)
    if open_browser:
        timer = threading.Timer(0.5, partial(webbrowser.open, url))
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv=None, default_root=None):
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog='gui-agent-bench-viewer', description='Browse saved and live run evidence.')
    parser.add_argument(
        'directory', nargs='?', type=Path, help='runs directory or a single run (default: <checkout>/runs)'
    )
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--no-open', action='store_true', help='print the URL without opening a browser')
    options = parser.parse_args(argv)
    root = options.directory or default_root or Path(__file__).resolve().parents[3] / 'runs'
    if not Path(root).is_dir():
        print(
            f'Viewer could not start: {root} is not a directory. Run an evaluation first, or pass a runs '
            'directory, for example: python scripts/view.py runs',
            file=sys.stderr,
        )
        return 1
    try:
        serve(root, options.port, open_browser=not options.no_open)
    except (OSError, ValueError) as exc:
        import errno

        hint = (
            f' Port {options.port} is in use; choose another with --port.'
            if isinstance(exc, OSError) and exc.errno == errno.EADDRINUSE
            else ''
        )
        print(f'Viewer could not start: {exc}.{hint}', file=sys.stderr)
        return 1
    return 0
