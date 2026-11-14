"""Capture a bounded real OpenCode process without exposing controller log mounts."""

import json
from pathlib import Path
import subprocess
import time

from gui_agent_bench.docker import docker, inspect
from gui_agent_bench.io import dump
from gui_agent_bench.arms import ARM_IDS
from gui_agent_bench.budgets import agent_steps, AGENT_LOG_BYTES
from gui_agent_bench.failures import Failure, issue, diagnostics


VERSION = '1.18.34'
# These are part of the pinned read-tool contract, not adjustable trial budgets.
READ_DEFAULT_LINES = 2000
READ_MAX_BYTES = 51200
READ_MAX_LINE_UNITS = 2000  # JavaScript UTF-16 code units, not Python code points.
READ_LINE_CLIP = '... (line truncated to 2000 chars)'
# Pinned client text sent as a trailing assistant turn on the agent's last step.
MAX_STEPS_NOTICE = '''CRITICAL - MAXIMUM STEPS REACHED

The maximum number of steps allowed for this task has been reached. Tools are disabled until next user input. Respond with text only.

STRICT REQUIREMENTS:
1. Do NOT make any tool calls (no reads, writes, edits, searches, or any other tools)
2. MUST provide a text response summarizing work done so far
3. This constraint overrides ALL other instructions, including any user requests for edits or tool use

Response must include:
- Statement that maximum steps for this agent have been reached
- Summary of what has been accomplished so far
- List of any remaining tasks that were not completed
- Recommendations for what should be done next

Any attempt to use tools is a critical violation. Respond with text ONLY.'''


def configuration(
    root: Path, destination: Path, provider: str, model: str, arm='judge_visual', platform='web', variant=None
) -> dict:
    if arm not in ARM_IDS:
        raise ValueError('arm not implemented')
    config = json.loads((root / f'configs/opencode/{arm}.json').read_text())
    if platform == 'tv':
        from gui_agent_bench.tv import TV_ARMS

        if arm not in TV_ARMS:
            raise ValueError('TV UI arms are unavailable')
        for tool in ('gui_dump_ui', 'gui_open_url'):
            config['permission'].pop(tool, None)
    if arm != 'judge_visual':
        # OpenCode 1.18.34 embeds Bun 1.3.14, whose fetch pool can reuse an
        # HTTP/1.0 socket while the broker closes it, even with a close response
        # header. Disable pooling for these stateless, local MCP requests.
        config['mcp'] = {
            'gui': {
                'type': 'remote',
                'url': 'http://browser:8081/mcp',
                'enabled': True,
                'oauth': False,
                'headers': {'Connection': 'close'},
            }
        }
    # Pinned OpenCode resolves non-Git projects to worktree '/'. Its file tools
    # check paths relative to that worktree, not absolute paths. The workspace
    # manifest forbids .git, so this translation has a stable root.
    for tool in ('read', 'edit'):
        config['permission'][tool] = {path.lstrip('/'): action for path, action in config['permission'][tool].items()}
    config.update(
        {
            'enabled_providers': [provider],
            'snapshot': False,
            'model': provider + '/' + model,
            'small_model': provider + '/' + model,
        }
    )
    config['agent']['bench']['steps'] = agent_steps(arm)
    config['provider'] = {
        provider: {
            'npm': '@ai-sdk/openai-compatible',
            'name': 'Isolated inference endpoint',
            'options': {'baseURL': 'http://provider:8080/v1', 'apiKey': 'relay-local'},
            'models': {
                model: {
                    'name': model,
                    'attachment': True,
                    'tool_call': True,
                    'limit': {'context': 128000, 'output': 4096},
                    'modalities': {'input': ['text', 'image'], 'output': ['text']},
                }
            },
        }
    }
    if variant is not None:
        # The pinned client applies --variant only to a reasoning-capable model.
        # It then sends the OpenAI-compatible reasoning_effort field, which the
        # relay requires on every agent turn. Without a variant the model entry
        # stays unchanged, so the default profile is identical to earlier runs.
        config['provider'][provider]['models'][model].update(
            {'reasoning': True, 'variants': {variant: {'reasoningEffort': variant}}}
        )
    # Use a neutral alias for OpenRouter to avoid its built-in SDK override.
    dump(destination, config)
    return config


def run(name: str, logs: Path, timeout: int) -> dict:
    logs.mkdir(parents=True, exist_ok=True)
    trajectory = logs / 'trajectory.ndjson'
    stderr = logs / 'stderr.log'
    start = time.monotonic()
    failure = None
    limits = []
    with trajectory.open('wb') as stdout, stderr.open('wb') as errors:
        process = subprocess.Popen(['docker', 'start', '-a', name], stdout=stdout, stderr=errors)
        while process.poll() is None:
            if time.monotonic() - start > timeout:
                failure = 'agent_timeout'
                if failure not in limits:
                    limits.append(failure)
            if trajectory.stat().st_size + stderr.stat().st_size > AGENT_LOG_BYTES:
                failure = 'agent_log_budget_exceeded'
                if failure not in limits:
                    limits.append(failure)
            if failure:
                docker('kill', name, check=False)
                process.wait(timeout=15)
                break
            time.sleep(0.2)
    state = inspect(name)['State']
    if trajectory.stat().st_size + stderr.stat().st_size > AGENT_LOG_BYTES:
        failure = 'agent_log_budget_exceeded'
        if failure not in limits:
            limits.append(failure)
    issues = []
    for limit in limits:
        cause = 'execution_timeout' if limit == 'agent_timeout' else 'evidence_overflow'
        issues.append(issue(Failure(cause), phase='authoring', operation='agent_process', impact='zero_credit'))
    if process.returncode != 0 or state['ExitCode'] != 0:
        issues.append(
            issue(Failure('process_error'), phase='authoring', operation='agent_process', impact='zero_credit')
        )
    events = []
    for line in trajectory.read_text(encoding='utf-8').splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except ValueError:
                issues.append(
                    issue(
                        Failure('incomplete_trajectory'),
                        phase='authoring',
                        operation='read_trajectory',
                        impact='zero_credit',
                    )
                )
    issues.extend(event_issues(events))
    summary = {
        'opencode_version': VERSION,
        'event_count': len(events),
        'elapsed_seconds': round(time.monotonic() - start, 3),
        'diagnostics': diagnostics(issues),
    }
    dump(logs / 'summary.json', summary)
    if issues:
        error = Failure(issues[0]['cause'])
        error.diagnostic_issues = issues
        raise error
    return summary


def validate_events(events: list[dict]) -> None:
    issues = event_issues(events)
    if issues:
        raise Failure(issues[0]['cause'])


def _read_state(event):
    part = event.get('part', {})
    if isinstance(part, dict) and event.get('type') == 'tool_use' and part.get('tool') == 'read':
        state = part.get('state', {})
        return state if isinstance(state, dict) else {}
    return {}


def _read_line_clipped(event):
    state = _read_state(event)
    metadata = state.get('metadata', {})
    display = metadata.get('display', {}) if isinstance(metadata, dict) else {}
    if not isinstance(display, dict):
        return False
    text = display.get('text')
    # OpenCode clips long lines even at EOF, where truncated can be false.
    return (
        display.get('type') == 'file'
        and isinstance(text, str)
        and any(
            line.endswith(READ_LINE_CLIP)
            and len(line[: -len(READ_LINE_CLIP)].encode('utf-16-le', errors='surrogatepass')) == 2 * READ_MAX_LINE_UNITS
            for line in text.split('\n')
        )
    )


def _pagination_flags(event):
    """Exempt only the two known flags of a complete pinned text-read page.

    More file lines being available is not evidence loss. Byte/line capping,
    unknown formats and inconsistent ranges remain fail-closed. No filesystem
    access or requirement to inspect unchosen evidence is introduced here.
    """
    state = _read_state(event)
    args = state.get('input', {})
    metadata = state.get('metadata', {})
    if not isinstance(args, dict) or not isinstance(metadata, dict):
        return set()
    display = metadata.get('display', {})
    if not isinstance(display, dict):
        return set()
    start, limit = args.get('offset', 1), args.get('limit', READ_DEFAULT_LINES)
    end, total = display.get('lineEnd'), display.get('totalLines')
    text, path = display.get('text'), args.get('filePath')
    if (
        state.get('status') != 'completed'
        or display.get('type') != 'file'
        or metadata.get('truncated') is not True
        or display.get('truncated') is not True
        or not all(type(n) is int and n > 0 for n in (start, limit, end, total))
        or type(display.get('lineStart')) is not int
        or display['lineStart'] != start
        or end != start + limit - 1
        or end >= total
        or not isinstance(path, str)
        or not path.startswith('/')
        or '\n' in path
        or display.get('path') != path
        or not isinstance(text, str)
        or _read_line_clipped(event)
    ):
        return set()
    lines = text.split('\n')
    if (
        len(lines) != limit
        or len(text.encode('utf-8', errors='surrogatepass')) > READ_MAX_BYTES
        or any(len(line.encode('utf-16-le', errors='surrogatepass')) > 2 * READ_MAX_LINE_UNITS for line in lines)
    ):
        return set()
    numbered = '\n'.join(f'{start + i}: {line}' for i, line in enumerate(lines))
    expected = (
        f'<path>{path}</path>\n<type>file</type>\n<content>\n{numbered}'
        f'\n\n(Showing lines {start}-{end} of {total}. '
        f'Use offset={end + 1} to continue.)\n</content>'
    )
    # Check the actual model-facing response, not just metadata claiming it is
    # complete. In particular, the distinct "Output capped" footer is rejected.
    if state.get('output') != expected:
        return set()
    base = ('part', 'state', 'metadata')
    return {base + ('truncated',), base + ('display', 'truncated')}


def event_issues(events):
    issues = []

    def add(cause, index=None):
        issues.append(
            issue(
                Failure(cause),
                phase='authoring',
                operation='agent_events',
                impact='zero_credit',
                source={'file': 'logs/agent/trajectory.ndjson', 'record_index': index},
            )
        )

    finishes = [event.get('part', {}).get('reason') for event in events if event.get('type') == 'step_finish']
    for index, event in enumerate(events):
        causes = set()

        def add_once(cause):
            if cause not in causes:
                add(cause, index)
                causes.add(cause)

        if event.get('type') == 'error':
            add_once('unknown_operation_error')
        exempt = _pagination_flags(event)
        if _read_line_clipped(event):
            add_once('evidence_overflow')
        pending = [((), event)]
        while pending:
            path, item = pending.pop()
            if isinstance(item, dict):
                if item.get('type') == 'compaction' or item.get('reason') == 'length':
                    add_once('context_overflow')
                if any(
                    item.get(flag) is True and path + (flag,) not in exempt for flag in ('truncated', 'isTruncated')
                ):
                    add_once('evidence_overflow')
                pending.extend((path + (key,), value) for key, value in item.items())
            elif isinstance(item, list):
                pending.extend((path + (i,), value) for i, value in enumerate(item))
    if not finishes or finishes[-1] != 'stop':
        add('incomplete_trajectory')
    return issues
