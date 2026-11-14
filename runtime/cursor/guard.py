"""Local deny-by-default guard; the independent MCP bridge is authoritative."""

import json
from pathlib import Path
import re
import sys


def main():
    allowed = False
    try:
        data = sys.stdin.buffer.read(1_048_577)
        if len(data) > 1_048_576:
            raise ValueError()
        value = json.loads(data)
        policy = json.loads(Path('/policy/agent.json').read_text())
        event = sys.argv[1]
        name = value.get('tool_name')
        if event == 'preToolUse':
            allowed = name in policy['tool_names']
        elif event == 'beforeMCPExecution':
            allowed = value.get('server') == 'bench' and value.get('tool_name') in policy['tools']
        # No native reads, commands, subagents, edits or compaction are admitted.
        row = {
            'event': event,
            'allowed': allowed,
            'tool': (
                name if isinstance(name, str) and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9:.-]{0,127}', name) else 'unknown'
            ),
        }
        with Path('/run/guard.ndjson').open('a') as stream:
            stream.write(json.dumps(row) + '\n')
    except Exception:
        pass
    print(
        json.dumps(
            {
                'permission': 'allow' if allowed else 'deny',
                'continue': allowed,
                'user_message': 'Benchmark tool policy.',
            }
        )
    )
    if not allowed:
        sys.exit(2)


if __name__ == '__main__':
    main()
