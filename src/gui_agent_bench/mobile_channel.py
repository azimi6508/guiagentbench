"""One private driver exchange via docker-exec stdin/stdout. No published port."""

import json
import sys
import urllib.request


def main():
    message = json.loads(sys.stdin.buffer.read(2100000))
    if set(message) != {'secret', 'path', 'value'} or message['path'] not in {'/ready', '/next', '/result'}:
        raise ValueError('private driver protocol denied')
    request = urllib.request.Request(
        'http://127.0.0.1:8001' + message['path'],
        data=json.dumps(message['value']).encode(),
        headers={'Authorization': message['secret'], 'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        print(json.dumps(json.load(response)))


if __name__ == '__main__':
    main()
