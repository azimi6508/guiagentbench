"""Loopback-only HTTP transport for the read-only viewer, using the Python stdlib."""

from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit
import webbrowser

from .evidence import EvidenceIndex

STATIC = Path(__file__).with_name('static')


class ViewerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root, port=8080):
        self.index = EvidenceIndex(root)
        super().__init__(('127.0.0.1', port), Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = 'GUIAgentBenchViewer/1'

    def log_message(self, *args):
        pass

    def send(self, data, mime='application/json; charset=utf-8', status=200):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=True, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header(
            'Content-Security-Policy',
            "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        )
        try:
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

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

        try:
            if request.path in {'/', '/app.js', '/hierarchy.js', '/review.js', '/trajectory.js', '/style.css'}:
                name = 'index.html' if request.path == '/' else request.path[1:]
                mime = (
                    'text/html'
                    if name.endswith('.html')
                    else 'text/css' if name.endswith('.css') else 'text/javascript'
                )
                self.send((STATIC / name).read_bytes(), mime + '; charset=utf-8')
            elif request.path == '/api/hierarchy':
                self.send(self.server.index.hierarchy())
            elif request.path == '/api/runs':
                self.send(self.server.index.listing())
            elif request.path == '/api/run':
                self.send(self.server.index.detail(arg('id')))
            elif request.path == '/api/events':
                offset, limit = int(arg('offset', '0')), int(arg('limit', '60'))
                if offset < 0 or not 1 <= limit <= 100:
                    raise ValueError('Invalid page')
                self.send(self.server.index.events(arg('id'), arg('path'), offset, limit))
            elif request.path == '/api/image':
                mime, data = self.server.index.embedded_image(arg('id'), arg('path'), int(arg('line')), arg('sha'))
                self.send(data, mime)
            elif request.path == '/api/artifact':
                path = self.server.index.artifact(arg('id'), arg('path'))
                self.send(path.read_bytes(), 'image/png' if path.suffix == '.png' else 'text/plain; charset=utf-8')
            else:
                self.send({'error': 'Not found'}, status=404)
        except FileNotFoundError:
            self.send({'error': 'Evidence not recorded yet or missing'}, status=404)
        except (ValueError, UnicodeError):
            self.send({'error': 'Invalid request or unreadable evidence'}, status=400)
        except OSError:
            self.send({'error': 'Evidence is temporarily unavailable'}, status=409)
        except (TypeError, AttributeError, KeyError, RecursionError):
            self.send(
                {'error': 'This record has an unsupported or malformed structure; original evidence is retained'},
                status=422,
            )

    def do_POST(self):
        self.send({'error': 'The viewer is read-only'}, status=405)

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST


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
