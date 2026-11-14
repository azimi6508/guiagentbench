"""Synthetic catalog/image stand-in, used only by actual-client controls."""

import http.server
import json
from pathlib import Path
import threading
import anyio
from gui_agent_bench.codex_bridge import catalog, serve
from gui_agent_bench.coordinates import observation_content

policy = json.loads(Path('/policy/bridge.json').read_text())
tools = [
    dict(t, name=t['name'][4:])
    for t in catalog(policy['arm'], policy['platform'], policy.get('environment_profile', 'generic'))
    if t['name'].startswith('gui_')
]


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        method = request['method']
        if method == 'notifications/initialized':
            self.send_response(202)
            self.end_headers()
            return
        if method == 'initialize':
            result = {
                'protocolVersion': '2024-11-05',
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'synthetic-control', 'version': '1'},
            }
        elif method == 'tools/list':
            result = {'tools': tools}
        elif method == 'tools/call' and request['params']['name'] == 'observe':
            result = {
                'content': observation_content(
                    Path('/policy/control.png').read_bytes(), policy['viewport'], policy['platform']
                ),
                'isError': False,
            }
        elif method == 'tools/call' and request['params']['name'] == 'dump_ui':
            result = {'content': [{'type': 'text', 'text': '{"synthetic":true,"elements":[]}'}], 'isError': False}
        elif (
            method == 'tools/call'
            and request['params']['name'] == 'step'
            and policy.get('environment_profile') == 'native_extended'
            and request['params'].get('arguments')
            in [
                {'action': 'open_app', 'app': 'pro expense'},
                {'action': 'long_press', 'x': 360, 'y': 300},
                {'action': 'scroll', 'dx': 300, 'dy': 0, 'x': 360, 'y': 598},
            ]
        ):
            result = {
                'content': [{'type': 'text', 'text': json.dumps({'fixture_received': request['params']['arguments']})}],
                'isError': False,
            }
        else:
            self.send_error(403)
            return
        data = json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


server = http.server.HTTPServer(('127.0.0.1', 8081), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
anyio.run(serve)
