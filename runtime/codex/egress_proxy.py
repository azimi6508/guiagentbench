"""CONNECT-only TLS tunnel. Never inspects or records tunneled plaintext."""

import ipaddress
import json
import select
import socket
import socketserver
import threading
import time

ALLOWED = {'chatgpt.com', 'auth.openai.com'}
SLOTS = threading.BoundedSemaphore(16)


def destination(authority):
    if authority not in {host + ':443' for host in ALLOWED}:
        raise ValueError('Destination denied')
    host = authority[:-4]
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Nonpublic destination denied')
    return host, addresses[0]


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        if not SLOTS.acquire(False):
            return
        started = time.monotonic()
        host, outcome, counts = None, 'denied', [0, 0]
        remote = None
        try:
            self.request.settimeout(15)
            data = b''
            while b'\r\n\r\n' not in data:
                chunk = self.request.recv(1)
                if not chunk or len(data) >= 8192:
                    raise ValueError()
                data += chunk
            lines = data.decode('ascii', 'strict').split('\r\n')
            method, authority, version = lines[0].split(' ')
            if method != 'CONNECT' or version != 'HTTP/1.1':
                raise ValueError()
            for line in lines[1:-2]:
                name, value = line.split(':', 1)
                if name.lower() not in {'host', 'user-agent', 'proxy-connection'} or any(ord(c) < 32 for c in value):
                    raise ValueError()
            host, (family, kind, proto, _, address) = destination(authority)
            remote = socket.socket(family, kind, proto)
            remote.settimeout(15)
            remote.connect(address)  # validated address, no second DNS lookup
            self.request.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            outcome = 'connected'
            while True:
                ready, _, _ = select.select([self.request, remote], [], [], 60)
                if not ready:
                    outcome = 'idle_timeout'
                    break
                for source in ready:
                    chunk = source.recv(65536)
                    if not chunk:
                        return
                    index = 0 if source is self.request else 1
                    counts[index] += len(chunk)
                    (remote if index == 0 else self.request).sendall(chunk)
        except (OSError, ValueError, UnicodeError):
            try:
                self.request.sendall(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
            except OSError:
                pass
        finally:
            if remote:
                remote.close()
            print(
                json.dumps(
                    dict(
                        destination=host,
                        port=443,
                        outcome=outcome,
                        sent_bytes=counts[0],
                        received_bytes=counts[1],
                        elapsed_seconds=time.monotonic() - started,
                    )
                ),
                flush=True,
            )
            SLOTS.release()


if __name__ == '__main__':
    with socketserver.ThreadingTCPServer(('0.0.0.0', 8080), Handler) as server:
        server.daemon_threads = True
        server.serve_forever()
