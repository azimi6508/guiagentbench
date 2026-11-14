"""Credential-free upstream adapter for the production gateway/client control.

This runs only in the isolated scripted control, never an evaluated trial.
"""

import http.client
import importlib.util
import os

spec = importlib.util.spec_from_file_location('gateway', '/opt/bench/gateway.py')
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)
plain_connection = http.client.HTTPConnection
gateway.http.client.HTTPSConnection = lambda *a, **k: plain_connection('upstream', 8080, timeout=30)
os.environ['GAB_CURSOR_ACCESS_TOKEN'] = 'synthetic-control-only'
admit = gateway.State.admit


def synthetic_identity(self, path, data, selected, category, stream):
    if selected is not None and 'GAB_CURSOR_MODEL_IDENTITY' not in os.environ:
        if selected['model_id'] != 'fixture-model':
            raise ValueError('Unexpected synthetic control model')
        os.environ['GAB_CURSOR_MODEL_IDENTITY'] = selected['sha256']
    return admit(self, path, data, selected, category, stream)


gateway.State.admit = synthetic_identity
original = gateway.Handler.do_POST


def controlled_request(self):
    # The stand-in sends no credentials or evaluated content. Retain its exact
    # method for diagnosing holes in the actual-client protocol coverage.
    gateway.record({'event': 'control_request_path', 'path': self.path})
    return original(self)


gateway.Handler.do_POST = controlled_request
server = gateway.GatewayHTTPServer(('0.0.0.0', 8080), gateway.Handler)
server.daemon_threads = True
server.state = gateway.State()
server.serve_forever()
