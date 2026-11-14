"""Scripted Anthropic Messages upstream for credential-free actual-client controls.

Never used in an evaluated trial. It replays /policy/control-steps.json as
tool_use turns, then ends the turn, and records content hashes of every tool
result it receives so the control can prove original images were delivered.
"""

import base64
import hashlib
import http.server
import json
from pathlib import Path
import sys

STEPS = json.loads(Path('/policy/control-steps.json').read_text())
MODE = Path('/policy/control-mode').read_text().strip() if Path('/policy/control-mode').exists() else 'normal'
SEEN = {'requests': 0}


def emit(row):
    sys.stdout.write(json.dumps(row, sort_keys=True) + '\n')
    sys.stdout.flush()


def sse(events):
    return b''.join(b'event: ' + e['type'].encode() + b'\ndata: ' + json.dumps(e).encode() + b'\n\n' for e in events)


def results(message):
    rows = []
    for block in message.get('content') if isinstance(message.get('content'), list) else []:
        if block.get('type') != 'tool_result':
            continue
        content = (
            block.get('content')
            if isinstance(block.get('content'), list)
            else [{'type': 'text', 'text': block.get('content')}]
        )
        for item in content:
            if item.get('type') == 'image':
                rows.append(
                    {'type': 'image', 'sha256': hashlib.sha256(base64.b64decode(item['source']['data'])).hexdigest()}
                )
            else:
                text = str(item.get('text'))
                rows.append(
                    {
                        'type': 'text',
                        'sha256': hashlib.sha256(text.encode()).hexdigest(),
                        'fixture_received': text if text.startswith('{"fixture_received":') else None,
                    }
                )
        rows.append({'type': 'end', 'is_error': bool(block.get('is_error'))})
    return rows


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def reply(self, status, data, kind='application/json'):
        self.send_response(status)
        self.send_header('content-type', kind)
        self.send_header('content-length', str(len(data)))
        self.send_header('request-id', 'req_fixture_%d' % SEEN['requests'])
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        SEEN['requests'] += 1
        body = json.loads(self.rfile.read(int(self.headers['content-length'])))
        emit(
            {
                'event': 'upstream_request',
                'path': self.path,
                'model': body.get('model'),
                'credential_injected': self.headers.get('x-api-key') == 'synthetic-control-only'
                or self.headers.get('authorization') == 'Bearer synthetic-control-only',
                'tools': sorted(t['name'] for t in body.get('tools', [])),
                'results': results(body['messages'][-1]),
            }
        )
        if MODE == 'rate_limit':
            self.reply(
                429, json.dumps({'type': 'error', 'error': {'type': 'rate_limit_error', 'message': 'fixture'}}).encode()
            )
            return
        index = sum(1 for m in body['messages'] if m['role'] == 'assistant')
        if index < len(STEPS):
            step = STEPS[index]
            name = (
                step['name'][len('native:') :] if step['name'].startswith('native:') else 'mcp__bench__' + step['name']
            )
            blocks = [
                {
                    'type': 'content_block_start',
                    'index': 0,
                    'content_block': {
                        'type': 'tool_use',
                        'id': 'toolu_fixture_%02d' % index,
                        'name': name,
                        'input': {},
                    },
                },
                {
                    'type': 'content_block_delta',
                    'index': 0,
                    'delta': {'type': 'input_json_delta', 'partial_json': json.dumps(step['arguments'])},
                },
                {'type': 'content_block_stop', 'index': 0},
            ]
            stop = 'tool_use'
        else:
            blocks = [
                {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}},
                {
                    'type': 'content_block_delta',
                    'index': 0,
                    'delta': {'type': 'text_delta', 'text': 'Control complete.'},
                },
                {'type': 'content_block_stop', 'index': 0},
            ]
            stop = 'end_turn'
        events = [
            {
                'type': 'message_start',
                'message': {
                    'id': 'msg_fixture_%d' % SEEN['requests'],
                    'type': 'message',
                    'role': 'assistant',
                    'model': body['model'],
                    'content': [],
                    'stop_reason': None,
                    'stop_sequence': None,
                    'usage': {'input_tokens': 100, 'output_tokens': 1},
                },
            },
            *blocks,
            {
                'type': 'message_delta',
                'delta': {'stop_reason': stop, 'stop_sequence': None},
                'usage': {'output_tokens': 20},
            },
            {'type': 'message_stop'},
        ]
        self.reply(200, sse(events), 'text/event-stream')


http.server.ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
