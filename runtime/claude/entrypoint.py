"""Start the pinned Claude Code client with a placeholder credential only.

The real Anthropic credential never enters this container: the per-trial
gateway replaces the placeholder. Built-in tools are disabled; the only tools
are the bench MCP server's, reached through the evidence-recording transport.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

PLACEHOLDERS = {
    'api_key': ('ANTHROPIC_API_KEY', 'sk-ant-api03-bench-placeholder'),
    'oauth': ('CLAUDE_CODE_OAUTH_TOKEN', 'sk-ant-oat01-bench-placeholder'),
}


def command(policy):
    return [
        '/opt/claude/claude',
        '--print',
        '--output-format',
        'stream-json',
        '--verbose',
        '--model',
        policy['model'],
        '--effort',
        policy['effort'],
        '--tools',
        '',
        '--strict-mcp-config',
        '--mcp-config',
        '/policy/mcp.json',
        '--allowedTools',
        ','.join(policy['tool_names']),
        '--permission-mode',
        'dontAsk',
        '--setting-sources',
        '',
        '--settings',
        '/policy/settings.json',
        '--no-session-persistence',
        '--disable-slash-commands',
    ]


def main():
    if sys.argv[1:]:
        raise ValueError('Unknown runtime mode')
    policy = json.loads(Path('/policy/agent.json').read_text())
    Path('/run/guard.ndjson').touch(exist_ok=False)
    for path in ('/run/home', '/run/tmp'):
        Path(path).mkdir(mode=0o700)
    name, value = PLACEHOLDERS[policy['auth_kind']]
    environment = dict(os.environ)
    environment[name] = value
    # Every background or helper request is bound to the single selected model;
    # the gateway independently rejects any other model.
    for key in (
        'ANTHROPIC_SMALL_FAST_MODEL',
        'ANTHROPIC_DEFAULT_HAIKU_MODEL',
        'ANTHROPIC_DEFAULT_SONNET_MODEL',
        'ANTHROPIC_DEFAULT_OPUS_MODEL',
        'CLAUDE_CODE_SUBAGENT_MODEL',
    ):
        environment[key] = policy['model']
    child = subprocess.Popen(command(policy), env=environment, stdin=subprocess.PIPE)
    child.stdin.write(policy['instruction'].encode('utf-8'))
    child.stdin.close()
    code = child.wait()
    Path('/run/child.json').write_text(json.dumps({'exit_code': code}))
    print(json.dumps({'type': 'bench_child_exit', 'exit_code': code}), flush=True)
    # Keep tmpfs evidence available to the host until it has been exported.
    deadline = time.monotonic() + 60
    while not Path('/run/shutdown').exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    sys.exit(code)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        sys.stderr.write('Claude Code runtime control failed.\n')
        sys.exit(1)
