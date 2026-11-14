"""HTTP framing shared by the single-threaded GUI brokers."""

from http.server import BaseHTTPRequestHandler
import json


def serve_gui(server, adapter, platform):
    """Service Playwright's routed network callbacks between HTTP requests.

    Synchronous Playwright dispatches route handlers only while its event loop
    is running. Blocking in HTTPServer alone freezes those callbacks while the
    agent thinks. A short idle pump permits ordinary background progress; it
    does not wait for stability or delay observations until an app is ready.
    GUI operations and callbacks remain on the browser's owning thread.
    """
    if platform == 'web':

        def pump():
            if adapter.page is not None:
                adapter.page.wait_for_timeout(1)

        server.service_actions = pump
    try:
        server.serve_forever(poll_interval=0.05)
    finally:
        server.server_close()


class ClosingJSONHandler(BaseHTTPRequestHandler):
    def reply(self, status, body=None):
        data = json.dumps(body).encode() if body is not None else b''
        # Each handler serves one request. Advertise closure explicitly; the
        # OpenCode configuration also disables pooling on the client side.
        # Keeping sockets alive would also monopolize this single-threaded
        # server; GUI operations must stay on the adapter's owning thread.
        self.close_connection = True
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)
