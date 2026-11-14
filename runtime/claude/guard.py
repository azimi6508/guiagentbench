"""PreToolUse deny-by-default guard; the independent MCP bridge is authoritative."""

import json
from pathlib import Path
import re
import sys


def main():
    allowed = False
    name = None
    try:
        data = sys.stdin.buffer.read(1_048_577)
        if len(data) > 1_048_576:
            raise ValueError()
        value = json.loads(data)
        policy = json.loads(Path('/policy/agent.json').read_text())
        name = value.get('tool_name')
        server = value.get('mcp_server')
        allowed = (
            value.get('hook_event_name') == 'PreToolUse'
            and name in policy['tool_names']
            and (server is None or (isinstance(server, dict) and server.get('name') == 'bench'))
        )
        row = {
            'event': 'PreToolUse',
            'allowed': allowed,
            'tool': (
                name if isinstance(name, str) and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9:.-]{0,127}', name) else 'unknown'
            ),
        }
        with Path('/run/guard.ndjson').open('a') as stream:
            stream.write(json.dumps(row) + '\n')
    except Exception:
        allowed = False
    if not allowed:
        # Exit code 2 blocks the call; the message is returned to the model.
        sys.stderr.write('Benchmark tool policy.\n')
        sys.exit(2)
    # Allowed calls defer to the fixed permission allowlist; no override here.
    sys.exit(0)


if __name__ == '__main__':
    main()
