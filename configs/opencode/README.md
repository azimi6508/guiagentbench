# OpenCode profiles

There is one JSON profile per arm. The runner translates the virtual file policies into the pinned client's worktree-relative permission form, then verifies its effective configuration before each trial.

All tools start denied. Only allowlisted reads, output edits and the exact broker catalog are enabled. Shell execution, delegation, skills, LSP, search/fetch and arbitrary custom tools remain denied. Live arms connect to the trusted GUI broker; the recorded-screenshot judgment arm needs no live application access.

Run the `bench` primary agent with isolated home, configuration and session stores. Do not merge a developer's personal configuration. Configuration files are read-only, and only the declared output directory is writable through the agent's editing tools.

Automatic compaction, sharing and evidence pruning are disabled. The controller detects incomplete trajectories, context overflow and unsupported client versions explicitly. Workspace, process and network isolation enforce the boundaries alongside the client permissions.

The exact client version and startup behavior are pinned in `runtime/agent/`. See [architecture](../../docs/architecture.md) and [runner setup](../../docs/runners.md).
