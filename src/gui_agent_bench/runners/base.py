"""Small, credential-free authoring contracts shared by the two runners."""

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentSpec:
    identifier: str
    runner: str
    model: str
    auth_mode: str
    reasoning_effort: str | None
    tool_profile: str
    budget_profile: str

    def record(self):
        return asdict(self)


@dataclass(frozen=True)
class AuthoringContext:
    trial_id: str
    arm: str
    platform: str
    viewport: tuple[int, int]
    public_workspace: Path
    workspace_manifest: dict
    output_directory: Path
    config_directory: Path
    log_directory: Path
    gui_network: str
    broker_container: str | None
    timeout_seconds: int
    environment_profile: str = 'generic'
    fixture_record: dict | None = None


@dataclass(frozen=True)
class AuthoringResult:
    runner: str
    completed: bool
    elapsed_seconds: float
    usage: dict | None
    diagnostics: dict
    capability_record: dict
    shutdown_reason: str
