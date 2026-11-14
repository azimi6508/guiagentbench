# Arm policies

Each TOML file is a complete default-deny allowlist for one evaluation arm. Paths refer to the isolated agent workspace. Unlisted files, tools and environment variables are denied. Inputs are read-only; editing is confined to the arm's output directory.

`steps = "optional"` permits recorded steps without requiring them for `judge_visual`. Screenshot globs describe admitted media, and the materializer resolves and hashes explicit files in their original order. File reads reject traversal and link escapes.

Provider names declare credential types supported by the framework. The selected credential belongs to the inference relay, never to the evaluated tool process. Runtime environment names are synthesized from explicit allowlists.

The tool broker filters discovery and invocation. Visual arms cannot use hidden-structure selectors or UI dumps. Judge-test agents can inspect the public test source but cannot execute it. Generated programs are written as artifacts and executed only by the separate verifier.

OpenCode, restricted Codex, Cursor and Claude Code share these arm contracts. Each runner also has its own runtime environment, process/network boundary and credential rules. See [runner configuration](../../docs/runners.md).
