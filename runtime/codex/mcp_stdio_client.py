"""Byte-transparent, fixed-destination, one-connection MCP transport."""

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
    selector.register(sys.stdin.buffer, selectors.EVENT_READ, 'stdin')
    selector.register(connection, selectors.EVENT_READ, 'socket')
    try:
        while True:
            for key, _ in selector.select():
                if key.data == 'stdin':
                    data = os.read(0, 65536)
                    if data:
                        connection.sendall(data)
                    else:
                        selector.unregister(sys.stdin.buffer)
                        connection.shutdown(socket.SHUT_WR)
                else:
                    data = connection.recv(65536)
                    if not data:
                        return
                    view = memoryview(data)
                    while view:
                        count = os.write(1, view)
                        view = view[count:]
    finally:
        selector.close()
        connection.close()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError):
        sys.exit(1)
