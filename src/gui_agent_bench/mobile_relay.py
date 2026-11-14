"""Private Docker-to-host rendezvous. No ADB listener crosses the boundary.

8000 is reachable only on the trusted application network. 8001 binds only
container loopback; the host uses docker-exec stdio with a per-session secret.
The secret is supplied on stdin, never in an image, argument or environment.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import queue
import sys
import threading
import time
import uuid
from gui_agent_bench.failures import Failure, cause_of


class Rendezvous:
    """One outstanding device operation, independent of HTTP response delivery.

    A client timeout does not cancel device work. Keep the slot occupied until
    the authenticated worker supplies its result; never overlap or retry work.
    """

    def __init__(self):
        self.pending = queue.Queue(maxsize=1)
        self.results = {}
        self.lock = threading.Lock()

    def submit(self, identity, value):
        channel = queue.Queue(maxsize=1)
        with self.lock:
            if self.results:
                raise Failure('native_operation_in_flight')
            self.pending.put_nowait({'id': identity, **value})
            self.results[identity] = channel
        return channel

    def complete(self, identity, value):
        with self.lock:
            channel = self.results.get(identity)
            if channel is None:
                raise Failure('infrastructure_error')
            channel.put_nowait(value)
            del self.results[identity]


def main():
    secret = sys.stdin.readline().strip()
    if len(secret) != 64:
        raise ValueError('missing driver rendezvous secret')
    rendezvous = Rendezvous()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            started, identity = time.monotonic(), None
            try:
                host = self.server.server_port == 8001
                if host and not hmac.compare_digest(self.headers.get('Authorization', ''), secret):
                    return self.reply(403, {'error': True})
                length = int(self.headers.get('Content-Length', '0'))
                if self.headers.get('Transfer-Encoding') or not 0 < length <= (2000000 if host else 16384):
                    raise ValueError('request budget')
                value = json.loads(self.rfile.read(length))
                if host and self.path == '/ready' and value == {}:
                    return self.reply(200, {'ready': True})
                if host and self.path == '/next' and value == {}:
                    try:
                        return self.reply(200, rendezvous.pending.get(timeout=20))
                    except queue.Empty:
                        return self.reply(200, None)
                if host and self.path == '/result' and set(value) == {'id', 'result'}:
                    rendezvous.complete(value['id'], value['result'])
                    return self.reply(200, {})
                if not host and self.path == '/call' and set(value) == {'operation', 'arguments'}:
                    identity = uuid.uuid4().hex
                    channel = rendezvous.submit(identity, value)
                    return self.reply(200, channel.get(timeout=90))
                raise ValueError('endpoint denied')
            except Exception as exc:
                from gui_agent_bench.failure_detail import attach, detail
                from gui_agent_bench.failures import Failure, issue

                if isinstance(exc, queue.Empty):
                    exc = Failure('action_timeout')
                attach(
                    exc,
                    component='native_relay',
                    stage='relay_wait',
                    correlation_id=identity,
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                )
                failure = issue(exc, phase='native_driver', operation='relay', impact='operation_failed')
                print(json.dumps({'failure': failure}), flush=True)
                self.reply(400, {'error': True, 'cause': cause_of(exc), 'detail': detail(exc)})

    host_server = ThreadingHTTPServer(('127.0.0.1', 8001), Handler)
    threading.Thread(target=host_server.serve_forever, daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0', 8000), Handler).serve_forever()


if __name__ == '__main__':
    main()
