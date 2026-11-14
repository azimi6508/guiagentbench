"""Agent and evaluation budgets shared by the runner, relay, brokers and verifier."""

# Agent steps per authoring/judgment session, by responsibility.
AGENT_STEPS = {'judge': 100, 'oracle': 150, 'test': 200}
# Each generated artifact is executed this many times on each version.
EXECUTIONS_PER_VERSION = 5
# Time limit for one execution of a generated oracle or complete test.
EXECUTION_TIMEOUT_SECONDS = {'oracle': 60, 'test': 360}
# Time limit for checking one judgment verdict against its private label.
JUDGMENT_CHECK_SECONDS = 5
# Wall-clock limit for one paired attempt: preparation, agent sessions and evaluation.
PAIRED_ATTEMPT_SECONDS = 7200
# OpenCode also sends a title request, and steps can fan out into parallel tool
# calls, each costing several MCP POSTs (call, cancellation, reconnects).
EXTRA_PROVIDER_REQUESTS = 8
TOOL_CALLS_PER_STEP = 4
BROKER_POSTS_PER_STEP = 10
# Full-app screenshots stay in the history, roughly 20-100 KB per step.
PROVIDER_REQUEST_BYTES = 32_000_000
AGENT_LOG_BYTES = 64_000_000
DEFAULT_TIMEOUT_SECONDS = 3600
MAX_TIMEOUT_SECONDS = 7200


def agent_steps(arm: str) -> int:
    return AGENT_STEPS[arm.split('_', 1)[0]]


def execution_timeout(arm: str) -> int:
    return EXECUTION_TIMEOUT_SECONDS[arm.split('_', 1)[0]]


def planned_variants() -> list:
    """Interleave correct/faulty executions so both versions share runtime conditions."""
    return ['correct', 'faulty'] * EXECUTIONS_PER_VERSION


def provider_requests(arm: str) -> int:
    return agent_steps(arm) + EXTRA_PROVIDER_REQUESTS


def author_tool_calls(arm: str) -> int:
    return agent_steps(arm) * TOOL_CALLS_PER_STEP


def author_broker_posts(arm: str) -> int:
    return agent_steps(arm) * BROKER_POSTS_PER_STEP


def check_timeout(seconds: int) -> None:
    if not 1 <= seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError(f'timeout must be between 1 and {MAX_TIMEOUT_SECONDS} seconds')


def codex_budget(arm: str, timeout: int) -> dict:
    from gui_agent_bench.arms import ARM_IDS

    if arm not in ARM_IDS:
        raise ValueError('Unknown arm')
    check_timeout(timeout)
    calls = author_tool_calls(arm)
    return dict(
        profile='codex-bounded-v1',
        timeout_seconds=timeout,
        startup_seconds=120,
        tool_timeout_seconds=60,
        interrupt_seconds=5,
        model_steps=None,
        model_requests=None,
        per_request_output_token_cap=None,
        bridge_calls=calls,
        observed_tool_items=calls,
        evidence_bytes=64_000_000,
        incoming_frame_bytes=1_048_576,
        non_tool_frames=4096,
        result_frame_bytes=8_000_000,
        tool_text_bytes=65_536,
        output_files=128,
        output_bytes=4_000_000,
        output_directories=64,
        output_path_bytes=192,
        output_path_components=4,
        output_component_bytes=64,
    )
