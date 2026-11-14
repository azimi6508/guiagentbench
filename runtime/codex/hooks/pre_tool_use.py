"""Managed deny-by-default hook. The bridge is the independent authority."""

import json
from pathlib import Path
import re
import sys

POLICY_PREFIX = 'bench-hook-v1: tool_denied:'


def denial(reason):
    return {
        'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': reason,
        }
    }


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def main():
    try:
        data = sys.stdin.buffer.read(1_048_577)
        if len(data) > 1_048_576:
            raise ValueError()
        value = json.loads(data.decode('utf-8'), object_pairs_hook=unique)
        allowed = json.loads(Path('/config/tools.json').read_text())
        if (
            not isinstance(value, dict)
            or not isinstance(allowed, list)
            or not all(isinstance(t, str) for t in allowed)
            or value.get('hook_event_name') != 'PreToolUse'
            or not isinstance(value.get('tool_name'), str)
        ):
            raise ValueError()
        name = value['tool_name']
        if name in allowed:
            return
        # No arguments, paths, config contents or exception text enter feedback.
        identifier = name if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9:.-]{0,127}', name) else 'nonstandard_identifier'
        print(json.dumps(denial(POLICY_PREFIX + identifier)))
        return
    except Exception:
        pass
    print(json.dumps(denial('bench-hook-v1: hook_configuration_error')))


if __name__ == '__main__':
    main()
