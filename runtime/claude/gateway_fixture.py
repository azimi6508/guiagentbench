"""Run the production gateway against the scripted upstream; controls only.

The credential is a synthetic constant and the upstream is the fixture
provider on the control's internal network, never api.anthropic.com.
"""

import http.client
import importlib.util
import os

spec = importlib.util.spec_from_file_location('gateway', '/opt/bench/gateway.py')
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)
gateway.connection = lambda: http.client.HTTPConnection('upstream', 8080, timeout=60)
os.environ['GAB_CLAUDE_CREDENTIAL'] = 'synthetic-control-only'
server = gateway.GatewayHTTPServer(('0.0.0.0', 8080), gateway.Handler)
server.state = gateway.State()
server.serve_forever()
