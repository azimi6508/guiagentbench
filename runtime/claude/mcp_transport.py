"""Single-session MCP transport with complete, bounded delivery evidence."""

import base64
import json
import os
import selectors
import socket
import sys


def main():
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(30)
    connection.connect('/ipc/bench.sock')
    connection.settimeout(None)
    selector = selectors.DefaultSelector()
    selector.register(0, selectors.EVENT_READ, 'out')
    selector.register(connection, selectors.EVENT_READ, 'in')
    buffers = {'out': b'', 'in': b''}
    used = 0
    with open('/run/mcp.ndjson', 'xb') as evidence:
        while True:
            for key, _ in selector.select():
                direction = key.data
                chunk = os.read(0, 65536) if direction == 'out' else connection.recv(65536)
                if not chunk:
                    if buffers[direction]:
                        raise ValueError('Incomplete MCP frame')
                    return
                buffers[direction] += chunk
                if len(buffers[direction]) > 8_000_000:
                    raise ValueError('MCP frame overflow')
                while b'\n' in buffers[direction]:
                    line, buffers[direction] = buffers[direction].split(b'\n', 1)
                    row = (
                        json.dumps({'direction': direction, 'frame_base64': base64.b64encode(line).decode()}).encode()
                        + b'\n'
                    )
                    used += len(row)
                    if used > 64_000_000:
                        raise ValueError('MCP evidence overflow')
                    evidence.write(row)
                    evidence.flush()
                    payload = line + b'\n'
                    if direction == 'out':
                        connection.sendall(payload)
                    else:
                        view = memoryview(payload)
                        while view:
                            view = view[os.write(1, view) :]


if __name__ == '__main__':
    try:
        main()
    except Exception:
        sys.stderr.write('MCP transport failed.\n')
        sys.exit(1)
