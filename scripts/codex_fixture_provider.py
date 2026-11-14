#!/usr/bin/env python3
"""Test-only loopback Responses fixture, launched inside a network-none container.

No production runner imports this file. No auth files, API keys, real provider,
or network fallback are accepted. Requests and deterministic replies are retained.
"""
import http.server
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import tomllib


def main():
    home = Path('/run/codex')
    if any(home.iterdir()) or any(k in os.environ for k in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENROUTER_API_KEY')):
        raise ValueError('Fixture refuses credentials or existing session state')
    config = Path('/config/config.toml')
    value = tomllib.loads(config.read_text())
    fixture = value['model_providers']['fixture']
    if (
        value['model_provider'] != 'fixture'
        or fixture['base_url'] != 'http://127.0.0.1:8765/v1'
        or fixture['requires_openai_auth']
        or fixture['request_max_retries'] != 0
        or fixture['stream_max_retries'] != 0
        or fixture['supports_websockets']
    ):
        raise ValueError('Fixture provider does not match loopback-only contract')
    (home / 'config.toml').symlink_to(config)
    script = json.loads(Path('/fixture/steps.json').read_text())
    log = Path('/fixture-log')
    counter = 0

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_):
            pass

        def do_POST(self):
            nonlocal counter
            if (
                self.path != '/v1/responses'
                or self.headers.get('Authorization')
                or self.headers.get('Content-Encoding')
            ):
                self.send_error(400, 'Unexpected fixture request')
                return
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 8_000_000:
                self.send_error(413)
                return
            body = self.rfile.read(size)
            request = json.loads(body)
            counter += 1
            (log / f'request-{counter}.json').write_bytes(body)
            if counter > len(script):
                self.send_error(409, 'No scripted retry or fallback')
                return
            step = script[counter - 1]
            if step.get('http_error'):
                payload = json.dumps(step['http_error']).encode()
                self.send_response(step.get('status', 429))
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if step.get('malformed_sse') or step.get('stall'):
                payload = b'event: response.output_item.done\ndata: {broken\n\n'
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Connection', 'close')
                if not step.get('stall'):
                    self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.flush()
                if step.get('stall'):
                    time.sleep(20)
                else:
                    self.wfile.write(payload)
                    self.wfile.flush()
                    (log / f'reply-{counter}.sse').write_bytes(payload)
                self.close_connection = True
                return
            item = step['item']
            response = dict(
                id=f'resp_fixture_{counter}',
                object='response',
                created_at=1,
                model=request['model'],
                status='completed',
                output=[item],
                usage={
                    'input_tokens': 20,
                    'output_tokens': 5,
                    'total_tokens': 25,
                    'input_tokens_details': {'cached_tokens': 0},
                    'output_tokens_details': {'reasoning_tokens': 0},
                },
            )
            events = [
                ('response.created', {'response': dict(response, status='in_progress', output=[])}),
                ('response.output_item.added', {'output_index': 0, 'item': item}),
                ('response.output_item.done', {'output_index': 0, 'item': item}),
                ('response.completed', {'response': response}),
            ]
            wire = b''.join(
                ('event: ' + kind + '\ndata: ' + json.dumps(dict(type=kind, **data)) + '\n\n').encode()
                for kind, data in events
            )
            (log / f'reply-{counter}.sse').write_bytes(wire)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(wire)))
            if step.get('server_model'):
                self.send_header('openai-model', step['server_model'])
            self.end_headers()
            self.wfile.write(wire)
            self.wfile.flush()

    server = http.server.HTTPServer(('127.0.0.1', 8765), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        child = subprocess.run(['/opt/codex/bin/codex', 'app-server', '--listen', 'stdio://', '--strict-config'])
        (log / 'process.json').write_text(json.dumps({'exit_code': child.returncode, 'requests': counter}))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
